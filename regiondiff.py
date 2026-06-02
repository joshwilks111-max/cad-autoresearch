#!/usr/bin/env python3
"""
regiondiff.py - the "where am I wrong" authoring tool (pure addition; no harness edits).

The harness reward gives a SCALAR score. This gives an ACTIONABLE *regional*
correction:

    "volume +14% concentrated at z=8-20 (too fat); -8% at z=30-40 (too thin);
     4 holes found vs 6 expected, missing near (+/-45,18)."

It generalises a hand-rolled per-Z-band occupancy diff (runs/_ctc05_ioucmp.py) into
a reusable tool that does THREE things on ONE shared voxel grid (so there is ~zero
marginal cost over a single voxelisation):

  1. SIGNED CELL DIFF   -> total extra/missing volume %% + world-space centroid of the
                           largest connected blob of each (scipy.ndimage.label).
  2. PER-AXIS-BAND       -> signed delta%% per band along the long axis; flags bands
                           whose imbalance exceeds an adaptive threshold.
  3. HOLES (sections)    -> count inner loops at a few heights; diff cand vs GT hole
                           sets by nearest centroid -> "missing N near (x,y), extra M".

The product is the terse text report (``RegionDiff.text``) that ends with ONE
imperative correction line. Everything is also exposed as structured dataclass fields.

CLI:
    python regiondiff.py --cand <path> --ref <task_id-or-path>
        [--pitch N] [--bands 12] [--axis auto|x|y|z] [--align world|pca]
        [--holes section|off]

Importable:
    from regiondiff import regiondiff, RegionDiff
    rd = regiondiff(cand_mesh, ref_mesh, ...)   # -> RegionDiff (has .text + fields)

GT-LEAK CAVEAT: the output reveals ground-truth geometry. Use it grader-side or
interactively only. NEVER feed regiondiff output into a worker's spec/feedback on a
drawing-track task -- it would hand the agent the answer.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

# Reuse the harness's deterministic occupancy + PCA frame helpers (read-only).
from harness.geometry import _canonical_frame, _voxel_centers  # noqa: E402


# --------------------------------------------------------------------------- #
#  Data model
# --------------------------------------------------------------------------- #
@dataclass
class BandDiff:
    lo: float
    hi: float
    delta_pct: float          # signed (cand - GT) as % of the band's GT count
    cand_n: int
    gt_n: int
    flagged: bool             # exceeded the adaptive imbalance threshold

    @property
    def label(self) -> str:
        if not self.flagged:
            return ""
        if self.delta_pct >= 25:
            return "TOO FAT"
        if self.delta_pct <= -25:
            return "TOO THIN"
        return "too fat" if self.delta_pct > 0 else "too thin"


@dataclass
class Hole:
    center: tuple          # (x, y) in the section's local 2D frame -> mapped to world axes
    radius: float
    world_center: tuple    # (x, y, z) world coords at the section height
    section_h: float


@dataclass
class RegionDiff:
    text: str
    pitch: float
    axis: int                       # 0/1/2 == x/y/z long axis used for bands
    axis_name: str
    axis_len: float
    align: str
    cand_volume: float
    gt_volume: float
    vol_delta_pct: float
    cand_bbox: tuple
    gt_bbox: tuple
    extra_vol_pct: float            # cells in cand but not GT (too fat) as % of GT volume
    missing_vol_pct: float          # cells in GT but not cand (too thin) as % of GT volume
    extra_blob_center: tuple | None
    missing_blob_center: tuple | None
    bands: list = field(default_factory=list)        # list[BandDiff]
    cand_holes: list = field(default_factory=list)   # list[Hole]  (representative section)
    gt_holes: list = field(default_factory=list)
    holes_found: int = 0
    holes_expected: int = 0
    missing_holes: list = field(default_factory=list)   # list[(x,y,r)]
    extra_holes: list = field(default_factory=list)
    resized_holes: list = field(default_factory=list)   # list[(x,y,gt_r,cand_r)]
    notes: list = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


# --------------------------------------------------------------------------- #
#  Mesh loading
# --------------------------------------------------------------------------- #
# trimesh has NO OCC backend, so it cannot parse STEP — `trimesh.load("x.step")`
# silently fails. STEP must go through build123d's kernel import, then tessellate.
# Same pattern (and tolerance) as timetrial/grade_step.py so a STEP ref/candidate
# graded here matches the referee's mesh.
_STEP_TESS_TOL = 0.05


def _step_to_mesh(path: Path) -> trimesh.Trimesh:
    """import_step (OCC kernel) -> tessellate at the pinned tolerance -> trimesh.
    The path trimesh.load() can't do for STEP."""
    from build123d import import_step, export_stl
    try:
        solid = import_step(str(path))
    except Exception as e:
        raise SystemExit(
            f"could not import STEP {path}: {e!r}\n"
            "  -> export as AP242/AP203, mm units, a SOLID body (not a surface/mesh export)"
        )
    ws = Path(tempfile.mkdtemp(prefix=f"regiondiff_step_{os.getpid()}_"))
    stl = ws / "ref.stl"
    try:
        export_stl(solid, str(stl), tolerance=_STEP_TESS_TOL)
        mesh = trimesh.load(str(stl), force="mesh")
    except Exception as e:
        raise SystemExit(f"could not tessellate STEP {path}: {e!r}\n"
                         "  -> the imported solid may be invalid; heal it in CAD")
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        raise SystemExit(f"STEP {path} tessellated to an empty mesh")
    return mesh


def _load_mesh_path(path: Path, what: str) -> trimesh.Trimesh:
    """Load a geometry file by suffix: STEP via the OCC kernel; mesh formats via
    trimesh directly."""
    suffix = path.suffix.lower()
    if suffix in (".step", ".stp"):
        return _step_to_mesh(path)
    mesh = trimesh.load(str(path), force="mesh")
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        raise SystemExit(f"failed to load a {what} mesh from {path}")
    return mesh


def _load_candidate_mesh(path: Path, build_timeout: int = 120) -> trimesh.Trimesh:
    """Load a candidate. A .py is built via harness.run_candidate in a UNIQUE temp
    workspace (NEVER runs/manual -- shared-workspace race). A .step goes through the
    OCC kernel; .stl/.obj/.ply through trimesh."""
    if path.suffix.lower() == ".py":
        from harness import run_candidate
        code = path.read_text(encoding="utf-8")        # utf-8: candidates may carry em-dashes etc.
        ws = Path(tempfile.mkdtemp(prefix=f"regiondiff_{os.getpid()}_"))
        run = run_candidate(code, ws, timeout=build_timeout)
        if not run.ok or run.mesh is None:
            raise SystemExit(f"candidate build failed: {run.error}\n{run.stderr[-1500:]}")
        return run.mesh
    return _load_mesh_path(path, "candidate")


def _load_reference_mesh(ref: str) -> trimesh.Trimesh:
    """A reference is either a task_id (-> run_inner_loop.load_task + load_ground_truth)
    or a path to a .step/.stl. The task_id path is how a grader compares against the
    hidden GT; the path form is for ad-hoc A/B (a .step now routes through the OCC
    kernel, since trimesh cannot parse STEP)."""
    p = Path(ref)
    if p.exists() and p.suffix.lower() in (".step", ".stp", ".stl", ".obj", ".ply"):
        return _load_mesh_path(p, "reference")
    # treat as a task_id
    from run_inner_loop import load_task, load_ground_truth
    task = load_task(ref)
    gt_mesh, _gt_sig, _gt_hist = load_ground_truth(task)
    return gt_mesh


# --------------------------------------------------------------------------- #
#  Shared-grid occupancy (THE one subtlety: both meshes on ONE aligned grid)
# --------------------------------------------------------------------------- #
def _derive_pitch(cand: trimesh.Trimesh, gt: trimesh.Trimesh,
                  pitch: float | None) -> float:
    if pitch and pitch > 0:
        return float(pitch)
    exts = []
    for m in (cand, gt):
        e = np.asarray(m.extents, dtype=float)
        e = e[np.isfinite(e)]
        if e.size:
            exts.append(float(np.max(e)))
    max_ext = max(exts) if exts else 64.0
    # max_extent / 64, clamped ~2-6mm (spec).
    return float(np.clip(max_ext / 64.0, 2.0, 6.0))


def _shared_grid_centers(cand: trimesh.Trimesh, gt: trimesh.Trimesh, pitch: float):
    """Cell centres covering the UNION AABB at a single pitch, so a cell index means
    the same physical cell for both meshes (required for the signed diff). Returns
    (centers[N,3], lo[3], ncell[3])."""
    lo = np.minimum(cand.bounds[0], gt.bounds[0]).astype(float)
    hi = np.maximum(cand.bounds[1], gt.bounds[1]).astype(float)
    # pad half a cell so boundary geometry is captured
    lo = lo - pitch
    hi = hi + pitch
    ncell = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 1)
    axes = [lo[d] + (np.arange(ncell[d]) + 0.5) * pitch for d in range(3)]
    gx, gy, gz = np.meshgrid(axes[0], axes[1], axes[2], indexing="ij")
    centers = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    return centers, lo, ncell


def _occupancy_on_shared_grid(mesh: trimesh.Trimesh, centers: np.ndarray,
                              lo: np.ndarray, ncell: np.ndarray,
                              pitch: float) -> np.ndarray:
    """Boolean occupancy matrix (shape == ncell) for `mesh` on the shared grid.

    Primary path: mesh.contains() on the shared cell centres -- exact and inherently
    aligned. Fallback (non-watertight): voxelise the mesh independently, fill it, and
    RASTERISE its occupied centres onto the same shared integer grid via the shared
    origin/pitch -- so cells still align even though trimesh's own voxel grid uses a
    per-mesh transform offset."""
    grid = np.zeros(tuple(ncell), dtype=bool)
    use_contains = False
    try:
        use_contains = bool(mesh.is_watertight)
    except Exception:
        use_contains = False

    if use_contains:
        try:
            inside = mesh.contains(centers)
            return np.asarray(inside, dtype=bool).reshape(tuple(ncell))
        except Exception:
            pass  # fall through to the voxel-rasterise fallback

    # Fallback: voxelise + fill, then map occupied world centres -> shared indices.
    try:
        vg = trimesh.voxel.creation.voxelize(mesh, pitch=pitch)
        try:
            vg = vg.fill()
        except Exception:
            pass
        pts = np.asarray(vg.points, dtype=float)
    except Exception:
        pts = _voxel_centers(mesh, res=int(max(ncell)))   # last-resort harness helper
    if pts.ndim != 2 or len(pts) == 0:
        return grid
    idx = np.floor((pts - lo) / pitch).astype(int)
    idx = np.clip(idx, 0, ncell - 1)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return grid


def _pca_align_pair(cand: trimesh.Trimesh, gt: trimesh.Trimesh, pitch: float):
    """Bring BOTH meshes into a SHARED PCA canonical frame for align='pca'.

    Canonicalising each mesh independently (the naive ``_canonical_frame`` on each)
    is WRONG for a diff: two near-but-not-identical parts get slightly different
    eigenvectors and the residual axis-sign / permutation ambiguity leaves the frames
    misaligned, so the cell diff is dominated by a spurious rigid mismatch (huge
    phantom extra+missing). This mirrors what ``harness.geometry.iou`` does: derive
    ONE rotation from the GT, place GT in it, then resolve the candidate's residual
    sign/permutation by searching all 48 signed orthogonal transforms and keeping the
    one with the best occupancy overlap. Returns rebuilt (cand, gt) meshes."""
    from harness.geometry import _ortho_transforms

    cv = np.asarray(gt.vertices, dtype=float)
    gmean = cv.mean(axis=0)
    cov = np.cov((cv - gmean).T)
    _, vecs = np.linalg.eigh(cov)
    vecs = vecs[:, ::-1]                       # principal axis first (matches _canonical_frame)
    gt_v = (cv - gmean) @ vecs                 # GT in its PCA frame
    gt_aligned = trimesh.Trimesh(vertices=gt_v, faces=gt.faces, process=False)

    cand_v0 = (np.asarray(cand.vertices, dtype=float) - cand.vertices.mean(axis=0)) @ vecs

    # If GT's three PCA eigenvalues are distinct, the eigenvalue ORDER already fixes
    # the axis permutation, so only the 8 sign flips remain ambiguous -- searching the
    # full 48 then risks picking a spurious X<->Y swap on a near-rectangular part.
    # Rotationally-symmetric GT (two near-equal eigenvalues) cannot be in-plane aligned
    # by ANY axis-aligned transform; we flag that to the caller as unreliable.
    w = np.sort(np.linalg.eigvalsh(cov))[::-1]
    symmetric = bool(w[1] > 1e-9 and (((w[0] - w[1]) / w[1] < 0.05) or
                                      ((w[1] - w[2]) / w[1] < 0.05)))
    if symmetric:
        transforms = _ortho_transforms()           # full search; still won't fully align
    else:
        from itertools import product
        transforms = []
        for signs in product((1, -1), repeat=3):
            transforms.append(np.diag(signs).astype(float))

    # Coarse occupancy on a shared grid to score each candidate orientation.
    def coarse_occ(verts_a, verts_b, res=24):
        allpts = np.vstack([verts_a, verts_b])
        lo = allpts.min(axis=0)
        hi = allpts.max(axis=0)
        span = np.maximum(hi - lo, 1e-9)

        def g(v):
            idx = np.clip(np.floor((v - lo) / span * (res - 1)).astype(int), 0, res - 1)
            flat = idx[:, 0] * res * res + idx[:, 1] * res + idx[:, 2]
            grid = np.zeros(res ** 3, dtype=bool)
            grid[flat] = True
            return grid
        return g(verts_a), g(verts_b)

    best_R, best_iou = np.eye(3), -1.0
    for R in transforms:
        cand_R = cand_v0 @ R.T
        ga, gb = coarse_occ(cand_R, gt_v)
        inter = np.logical_and(ga, gb).sum()
        union = np.logical_or(ga, gb).sum()
        val = float(inter / union) if union else 0.0
        if val > best_iou:
            best_iou, best_R = val, R
    cand_aligned = trimesh.Trimesh(vertices=cand_v0 @ best_R.T, faces=cand.faces,
                                   process=False)
    return cand_aligned, gt_aligned, best_iou, symmetric


def _largest_blob_center(diff_grid: np.ndarray, lo: np.ndarray,
                         pitch: float) -> tuple | None:
    """World-space centroid of the largest 6-connected blob of True cells."""
    if not diff_grid.any():
        return None
    from scipy.ndimage import label
    lab, n = label(diff_grid)
    if n == 0:
        return None
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    big = int(sizes.argmax())
    cell_idx = np.argwhere(lab == big)
    ctr_cell = cell_idx.mean(axis=0)
    ctr_world = lo + (ctr_cell + 0.5) * pitch
    return tuple(np.round(ctr_world, 1))


# --------------------------------------------------------------------------- #
#  Long-axis selection + per-band profile
# --------------------------------------------------------------------------- #
def _pick_axis(mesh: trimesh.Trimesh, axis_arg: str) -> int:
    if axis_arg in ("x", "y", "z"):
        return {"x": 0, "y": 1, "z": 2}[axis_arg]
    ext = np.asarray(mesh.extents, dtype=float)
    ext = np.where(np.isfinite(ext), ext, 0.0)
    return int(np.argmax(ext))


def _band_profile(occ_c: np.ndarray, occ_g: np.ndarray, axis: int,
                  lo: np.ndarray, pitch: float, nbands: int) -> list:
    """Signed per-band material delta along `axis`. A band's delta% is
    (cand_count - gt_count) / max(gt_count, 1) * 100. The flag uses the prototype's
    adaptive threshold: abs(nc - ng) > max(40, 0.25 * max(ng, 1))."""
    # collapse the two non-axis dims -> per-slice occupied-cell counts
    other = tuple(d for d in range(3) if d != axis)
    cand_slice = occ_c.sum(axis=other)     # length == ncell[axis]
    gt_slice = occ_g.sum(axis=other)
    nslice = len(gt_slice)
    if nslice == 0:
        return []
    edges = np.linspace(0, nslice, nbands + 1).astype(int)
    bands: list[BandDiff] = []
    for b in range(nbands):
        s, e = edges[b], edges[b + 1]
        if e <= s:
            continue
        nc = int(cand_slice[s:e].sum())
        ng = int(gt_slice[s:e].sum())
        delta_pct = (nc - ng) / max(ng, 1) * 100.0
        flagged = abs(nc - ng) > max(40, 0.25 * max(ng, 1))
        world_lo = lo[axis] + s * pitch
        world_hi = lo[axis] + e * pitch
        bands.append(BandDiff(lo=round(world_lo, 1), hi=round(world_hi, 1),
                              delta_pct=round(delta_pct, 1),
                              cand_n=nc, gt_n=ng, flagged=flagged))
    return bands


# --------------------------------------------------------------------------- #
#  Holes via sections (shapely-free: section.entities + to_2D vertices only)
# --------------------------------------------------------------------------- #
def _section_loops(mesh: trimesh.Trimesh, axis: int, height: float):
    """Return [(area, center_xy, r_mean, r_cv)] for each closed loop of the section
    plane `axis = height`. Uses ONLY section.entities + 2D vertices (no shapely:
    .polygons_full / .area would crash). center_xy is in the section's local 2D frame
    aligned so x/y map back to the mesh's two non-axis world coords."""
    normal = np.zeros(3)
    normal[axis] = 1.0
    origin = np.zeros(3)
    origin[axis] = height
    try:
        sec = mesh.section(plane_origin=origin, plane_normal=normal)
    except Exception:
        return []
    if sec is None or len(sec.entities) == 0:
        return []

    # For an axis-aligned cut, the two in-plane world axes are the non-axis dims.
    inplane = [d for d in range(3) if d != axis]
    V3 = np.asarray(sec.vertices, dtype=float)
    loops = []
    for e in sec.entities:
        try:
            idx = np.asarray(e.points)
        except Exception:
            continue
        if len(idx) < 4:
            continue
        pv = V3[idx][:, inplane]          # (n,2) in real world coords of the two in-plane axes
        ctr = pv.mean(axis=0)
        r = np.linalg.norm(pv - ctr, axis=1)
        r_mean = float(r.mean())
        r_cv = float(r.std() / max(r_mean, 1e-9))
        x, y = pv[:, 0], pv[:, 1]
        area = 0.5 * abs(float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])))
        loops.append((area, ctr, r_mean, r_cv))
    return loops


def _holes_at(mesh: trimesh.Trimesh, axis: int, height: float,
              cv_max: float = 0.15) -> list:
    """Inner loops at a section height, classified as holes. The OUTER boundary is
    the loop with the largest shoelace area; every other closed loop is a candidate
    inner feature, ACCEPTED as a (round) hole only if r_std/r_mean < cv_max.

    cv_max=0.15: a clean bore sections to a near-perfect circle (cv ~0.01); gusset/wall
    junction loops and tangential grazes have cv 0.4-0.7. The old 0.35 admitted those
    junction artifacts as phantom 'holes' (measured: an L-bracket gusset edge -> a
    spurious r=11 'hole' at cv=0.44). 0.15 keeps real bores, drops the junk."""
    loops = _section_loops(mesh, axis, height)
    if len(loops) < 2:
        return []
    loops.sort(key=lambda t: -t[0])     # outer first (max area)
    holes = []
    for area, ctr, r_mean, r_cv in loops[1:]:
        if r_cv > cv_max:               # not circular enough -> not a hole
            continue
        wc = [0.0, 0.0, 0.0]
        inplane = [d for d in range(3) if d != axis]
        wc[inplane[0]] = round(float(ctr[0]), 1)
        wc[inplane[1]] = round(float(ctr[1]), 1)
        wc[axis] = round(float(height), 1)
        holes.append(Hole(center=(round(float(ctr[0]), 1), round(float(ctr[1]), 1)),
                          radius=round(r_mean, 2), world_center=tuple(wc),
                          section_h=round(float(height), 1)))
    return holes


def _section_heights(lo_a: float, hi_a: float, max_planes: int = 64,
                     step_mm: float = 4.0) -> list:
    """Section heights along one axis at ABSOLUTE ~step_mm spacing (interior 5%..95%).

    Review fix: the old 13-plane CAP made spacing false on big parts — a 200mm part
    got ~15mm spacing, so a bore whose run-length was under ~2 spacings could hit
    fewer than min_plane_hits planes and be silently dropped. Cap raised 13->64 so
    spacing stays ~step_mm up to 256mm; only beyond that does it coarsen. (A bore is
    detected on the axis it RUNS ALONG, where it spans the feature thickness and is
    sliced by many planes — so the cap, not face placement, is what fixes the big-part
    miss. Face-adjacent planes were tried and REVERTED: they section ~1.5mm off a face
    where edge-rounding/adjacent-hole mouths project as near-circular loops and add
    phantom 'holes' (regressed the L-bracket 4->5). A near-face BLIND hole stays a
    B-rep-cylinder-face job, consistent with the documented mesh-section limitation.)"""
    span = hi_a - lo_a
    if span < 1e-6:
        return []
    n = int(np.clip(np.ceil(span / step_mm), 3, max_planes))
    return [lo_a + f * span for f in np.linspace(0.05, 0.95, int(n))]


def _dedup_holes_3d(holes: list, tol: float) -> list:
    """Collapse holes within `tol` of each other (3D world center) into one, keeping the
    tightest-radius (lowest-CV proxy) representative. Used as the FINAL cross-axis merge
    after per-axis confirmation."""
    kept: list = []
    for h in sorted(holes, key=lambda x: x.radius):   # smaller/tighter first
        wc = np.asarray(h.world_center, dtype=float)
        if not any(np.linalg.norm(wc - np.asarray(k.world_center, dtype=float)) <= tol
                   for k in kept):
            kept.append(h)
    return kept


def _all_holes(mesh: trimesh.Trimesh, lo: np.ndarray, hi: np.ndarray,
               tol: float, min_plane_hits: int = 2) -> list:
    """Detect physical bores by sweeping ALL THREE axes with DENSE section planes, but
    only ACCEPT a bore that is confirmed on >= min_plane_hits planes OF THE SAME AXIS.

    Why per-axis confirmation: a real through-hole running along axis A is sliced cleanly
    by many of A's planes (stable in-plane center). A plane of a FOREIGN axis that merely
    grazes that bore tangentially yields a one-off partial arc at a slightly different
    place — it shows up on a single plane and is rejected. This kills the cross-axis
    over-count (one bore spawning spurious arcs on the other two axes) without loosening
    the dedup radius (which would wrongly merge two genuinely close holes).

    Three fixes over the original single-long-axis 3-fraction sweep: (1) all 3 axes,
    (2) dense ~4mm planes so a hole in a thin offset feature is sliced, (3) per-axis
    multi-plane confirmation so grazes don't inflate the count."""
    per_axis: list = []
    for ax in range(3):
        # bucket this axis's detections by rounded in-plane center
        buckets: dict = {}
        for h in _section_heights(float(lo[ax]), float(hi[ax])):
            for hole in _holes_at(mesh, ax, h):
                key = (round(hole.center[0], 0), round(hole.center[1], 0))
                buckets.setdefault(key, []).append(hole)
        # accept buckets confirmed on >= min_plane_hits planes; representative = median-ish
        for key, hits in buckets.items():
            if len(hits) >= min_plane_hits:
                hits.sort(key=lambda x: x.radius)
                per_axis.append(hits[len(hits) // 2])   # middle hit (robust center/radius)
    return _dedup_holes_3d(per_axis, tol)


def _match_holes(cand_holes: list, gt_holes: list, pitch: float):
    """Diff two hole sets by nearest 3D centroid (within ~2 pitch). Returns
    (missing[(x,y,z,r)], extra[(x,y,z,r)], resized[(x,y,z,gt_r,cand_r)]) where missing =
    in GT not matched in cand, extra = in cand not matched in GT, and resized = matched
    in position but the radius differs by more than ~1 pitch (a wrong-size bore /
    counterbore -- positionally correct but the diameter is off, which the centroid
    match alone would silently call a hit).

    Matches on WORLD_CENTER (3D): holes can now be detected on any of the three section
    axes, so their per-section 2D `center` frames are incommensurable — only the 3D
    world center is comparable across axes."""
    tol = max(2.0 * pitch, 3.0)
    # Radius is read directly off the section's 2D vertices (sub-pitch accurate,
    # independent of the voxel grid), so the resize tolerance can be tighter than a
    # full pitch -- a half-pitch (floored ~0.75mm) catches a wrong-size bore without
    # firing on identical geometry.
    r_tol = max(0.5 * pitch, 0.75)
    used = [False] * len(cand_holes)
    missing = []
    resized = []
    for gh in gt_holes:
        gc = np.asarray(gh.world_center, dtype=float)
        best, bi = tol + 1, -1
        for i, ch in enumerate(cand_holes):
            if used[i]:
                continue
            d = float(np.linalg.norm(np.asarray(ch.world_center, dtype=float) - gc))
            if d < best:
                best, bi = d, i
        if bi >= 0 and best <= tol:
            used[bi] = True
            if abs(cand_holes[bi].radius - gh.radius) > r_tol:
                resized.append((*[round(float(x), 1) for x in gh.world_center],
                                gh.radius, cand_holes[bi].radius))
        else:
            missing.append((*[round(float(x), 1) for x in gh.world_center], gh.radius))
    extra = [(*[round(float(x), 1) for x in ch.world_center], ch.radius)
             for i, ch in enumerate(cand_holes) if not used[i]]
    return missing, extra, resized


# --------------------------------------------------------------------------- #
#  Core
# --------------------------------------------------------------------------- #
def _bbox_tuple(mesh: trimesh.Trimesh) -> tuple:
    e = np.asarray(mesh.extents, dtype=float)
    e = np.where(np.isfinite(e), e, 0.0)
    return tuple(round(float(v), 1) for v in e)


def regiondiff(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
               pitch: float | None = None, bands: int = 12,
               axis: str = "auto", align: str = "world",
               holes: str = "section", cand_label: str = "candidate",
               ref_label: str = "ref") -> RegionDiff:
    """Compare a candidate mesh against a reference mesh and return a RegionDiff.

    align='world' compares them in their given frames (the common authoring case --
    candidate and GT already share a coordinate system). align='pca' brings BOTH into
    a SHARED PCA frame (GT-derived rotation + a 48-transform sign/permutation search
    on the candidate, like harness.geometry.iou) so a pure pose difference doesn't
    masquerade as a regional error. NOTE: world is preferred whenever cand and GT are
    already co-located -- pca can only resolve orientation up to symmetry and adds
    voxel noise, so a same-frame part diffs cleaner under world."""
    notes: list[str] = []

    cand = cand_mesh.copy()
    gt = ref_mesh.copy()

    pitch_v = _derive_pitch(cand, gt, pitch)

    if align == "pca":
        try:
            cand, gt, pca_iou, symmetric = _pca_align_pair(cand, gt, pitch_v)
            if symmetric or pca_iou < 0.6:
                why = ("rotationally-symmetric part (in-plane orientation is arbitrary)"
                       if symmetric else f"poor post-align overlap (IoU={pca_iou:.2f})")
                notes.append(f"PCA ALIGN UNRELIABLE: {why} -- the per-band / hole diff "
                             f"below may be dominated by residual pose, NOT real shape "
                             f"error. Re-run with --align world (cand & GT are usually "
                             f"already co-located in the harness).")
            else:
                notes.append(f"pca align: coarse overlap IoU={pca_iou:.2f} "
                             f"(orientation resolved up to symmetry)")
        except Exception as e:
            notes.append(f"pca align failed ({e!r}); fell back to world frame")
            cand, gt = cand_mesh.copy(), ref_mesh.copy()
            align = "world"

    pitch_v = _derive_pitch(cand, gt, pitch)
    axis_i = _pick_axis(gt, axis)
    axis_name = "XYZ"[axis_i]

    lo_u = np.minimum(cand.bounds[0], gt.bounds[0]).astype(float)
    hi_u = np.maximum(cand.bounds[1], gt.bounds[1]).astype(float)
    axis_len = float(hi_u[axis_i] - lo_u[axis_i])

    # --- shared grid occupancy ------------------------------------------------
    centers, lo, ncell = _shared_grid_centers(cand, gt, pitch_v)
    occ_c = _occupancy_on_shared_grid(cand, centers, lo, ncell, pitch_v)
    occ_g = _occupancy_on_shared_grid(gt, centers, lo, ncell, pitch_v)

    cell_vol = pitch_v ** 3
    gt_cells = int(occ_g.sum())
    extra_grid = occ_c & ~occ_g            # too fat / uncut hole / wrong-polarity boss
    missing_grid = (~occ_c) & occ_g        # too thin / missing feature / over-cut
    extra_cells = int(extra_grid.sum())
    missing_cells = int(missing_grid.sum())
    extra_vol_pct = extra_cells / max(gt_cells, 1) * 100.0
    missing_vol_pct = missing_cells / max(gt_cells, 1) * 100.0

    extra_blob = _largest_blob_center(extra_grid, lo, pitch_v)
    missing_blob = _largest_blob_center(missing_grid, lo, pitch_v)

    # --- true volumes (mesh, not voxel) for the headline ----------------------
    try:
        cv = float(abs(cand.volume))
    except Exception:
        cv = cell_vol * int(occ_c.sum())
    try:
        gv = float(abs(gt.volume))
    except Exception:
        gv = cell_vol * gt_cells
    vol_delta_pct = (cv - gv) / max(gv, 1e-9) * 100.0

    # --- per-band profile -----------------------------------------------------
    band_list = _band_profile(occ_c, occ_g, axis_i, lo, pitch_v, bands)

    # --- holes ----------------------------------------------------------------
    cand_holes_rep: list = []
    gt_holes_rep: list = []
    missing_holes: list = []
    extra_holes: list = []
    resized_holes: list = []
    holes_found = holes_expected = 0
    hole_section_hs = []
    dense = False
    if holes == "section":
        try:
            # Sweep ALL THREE axes (a hole runs along ONE axis; the old single-long-axis
            # sweep missed holes perpendicular to the band axis). Dedup to physical bores
            # by 3D world-center proximity at ~one hole-diameter tolerance.
            dedup_tol = max(3.0 * pitch_v, 4.0)
            cand_holes_rep = _all_holes(cand, lo_u, hi_u, dedup_tol)
            gt_holes_rep = _all_holes(gt, lo_u, hi_u, dedup_tol)
            hole_section_hs = [0.2, 0.5, 0.8]   # per-axis fractions (now all 3 axes)
            holes_found = len(cand_holes_rep)
            holes_expected = len(gt_holes_rep)
            # Dense field (e.g. CTC-05's 29 holes): don't enumerate; report counts.
            dense = holes_expected > 8 or holes_found > 8
            if not dense:
                missing_holes, extra_holes, resized_holes = _match_holes(
                    cand_holes_rep, gt_holes_rep, pitch_v)
        except Exception as e:
            notes.append(f"hole detection skipped ({e!r})")

    # --------------------------------------------------------------------------
    text = _render_text(
        cand_label=cand_label, ref_label=ref_label, pitch=pitch_v,
        axis_name=axis_name, axis_len=axis_len, align=align,
        cand_vol=cv, gt_vol=gv, vol_delta_pct=vol_delta_pct,
        cand_bbox=_bbox_tuple(cand), gt_bbox=_bbox_tuple(gt),
        extra_vol_pct=extra_vol_pct, missing_vol_pct=missing_vol_pct,
        extra_blob=extra_blob, missing_blob=missing_blob,
        bands=band_list, holes_mode=holes, hole_hs=hole_section_hs,
        holes_found=holes_found, holes_expected=holes_expected,
        missing_holes=missing_holes, extra_holes=extra_holes,
        resized_holes=resized_holes, dense=dense,
        notes=notes,
    )

    return RegionDiff(
        text=text, pitch=round(pitch_v, 2), axis=axis_i, axis_name=axis_name,
        axis_len=round(axis_len, 1), align=align,
        cand_volume=round(cv, 1), gt_volume=round(gv, 1),
        vol_delta_pct=round(vol_delta_pct, 1),
        cand_bbox=_bbox_tuple(cand), gt_bbox=_bbox_tuple(gt),
        extra_vol_pct=round(extra_vol_pct, 1),
        missing_vol_pct=round(missing_vol_pct, 1),
        extra_blob_center=extra_blob, missing_blob_center=missing_blob,
        bands=band_list, cand_holes=cand_holes_rep, gt_holes=gt_holes_rep,
        holes_found=holes_found, holes_expected=holes_expected,
        missing_holes=missing_holes, extra_holes=extra_holes,
        resized_holes=resized_holes, notes=notes,
    )


# --------------------------------------------------------------------------- #
#  Text rendering (THE PRODUCT: terse; ends with one imperative correction line)
# --------------------------------------------------------------------------- #
def _fmt_pt(p) -> str:
    if p is None:
        return "n/a"
    return "(" + ",".join(f"{v:g}" for v in p) + ")"


def _fmt_vol(v: float) -> str:
    if v >= 1e6:
        return f"{v/1e6:.1f}M"
    if v >= 1e3:
        return f"{v/1e3:.1f}k"
    return f"{v:.0f}"


def _render_text(*, cand_label, ref_label, pitch, axis_name, axis_len, align,
                 cand_vol, gt_vol, vol_delta_pct, cand_bbox, gt_bbox,
                 extra_vol_pct, missing_vol_pct, extra_blob, missing_blob,
                 bands, holes_mode, hole_hs, holes_found, holes_expected,
                 missing_holes, extra_holes, resized_holes, dense, notes) -> str:
    L = []
    over = "over" if vol_delta_pct >= 0 else "under"
    L.append(f"REGIONDIFF  cand={cand_label}  ref={ref_label}   "
             f"pitch={pitch:.1f}mm  axis={axis_name}(long, {axis_len:.0f}mm)  align={align}")
    bbox_ok = "OK" if np.allclose(cand_bbox, gt_bbox, atol=max(pitch, 0.5)) else "DIFF"
    L.append(f"vol: cand {_fmt_vol(cand_vol)} vs GT {_fmt_vol(gt_vol)}  "
             f"({vol_delta_pct:+.1f}% {over})   "
             f"bbox cand{list(cand_bbox)} vs GT{list(gt_bbox)} {bbox_ok}")
    L.append(f"cells: extra(cand-only) {extra_vol_pct:.1f}% of GT vol"
             + (f" @blob~{_fmt_pt(extra_blob)}" if extra_blob else "")
             + f";  missing(GT-only) {missing_vol_pct:.1f}%"
             + (f" @blob~{_fmt_pt(missing_blob)}" if missing_blob else ""))

    L.append(f"─ material by {axis_name}-band (Δ = cand−GT, % of band) ─")
    flagged = [b for b in bands if b.flagged]
    shown = flagged if flagged else []
    if not shown:
        L.append("  (no band exceeds the imbalance threshold — material is well-distributed)")
    for b in shown:
        tag = f"  {b.label}" if b.label else ""
        L.append(f"  {axis_name} {b.lo:g}–{b.hi:g}   {b.delta_pct:+.0f}%{tag}")

    if holes_mode == "section":
        hs = "/".join(f"{h:g}" for h in hole_hs) if hole_hs else "?"
        L.append(f"─ holes (all-axis section @ frac {hs}) ─")
        if dense:
            L.append(f"  found {holes_found}, GT has {holes_expected}  "
                     f"(dense field — counts only, not enumerated)")
        else:
            # Hole tuples are now (x, y, z, r) — centers are 3D (mixed section axes).
            mtxt = ""
            if missing_holes:
                near = "; ".join(f"({x:g},{y:g},{z:g}) r≈{r:g}"
                                 for x, y, z, r in missing_holes[:4])
                mtxt = f"  → MISSING {len(missing_holes)} near {near}"
            etxt = ""
            if extra_holes:
                near = "; ".join(f"({x:g},{y:g},{z:g}) r≈{r:g}"
                                 for x, y, z, r in extra_holes[:4])
                etxt = f";  extra {len(extra_holes)} near {near}"
            elif not missing_holes:
                etxt = ";  extra 0"
            rtxt = ""
            if resized_holes:
                near = "; ".join(f"({x:g},{y:g},{z:g}) r {cr:g}→GT {gr:g}"
                                 for x, y, z, gr, cr in resized_holes[:4])
                rtxt = f";  WRONG RADIUS {len(resized_holes)}: {near}"
            if not missing_holes and not extra_holes and not resized_holes:
                L.append(f"  found {holes_found}, GT has {holes_expected}  → holes MATCH")
            else:
                L.append(f"  found {holes_found}, GT has {holes_expected}{mtxt}{etxt}{rtxt}")

    # ---- the single imperative correction line -------------------------------
    L.append("OVERALL: " + _correction_line(
        vol_delta_pct=vol_delta_pct, axis_name=axis_name, bands=bands,
        extra_blob=extra_blob, missing_blob=missing_blob,
        extra_vol_pct=extra_vol_pct, missing_vol_pct=missing_vol_pct,
        holes_found=holes_found, holes_expected=holes_expected,
        missing_holes=missing_holes, extra_holes=extra_holes,
        resized_holes=resized_holes, dense=dense))

    for n in notes:
        L.append(f"note: {n}")
    return "\n".join(L)


def _correction_line(*, vol_delta_pct, axis_name, bands, extra_blob, missing_blob,
                     extra_vol_pct, missing_vol_pct, holes_found, holes_expected,
                     missing_holes, extra_holes, resized_holes, dense) -> str:
    parts = []
    fat = [b for b in bands if b.flagged and b.delta_pct > 0]
    thin = [b for b in bands if b.flagged and b.delta_pct < 0]
    if fat:
        b = max(fat, key=lambda x: x.delta_pct)
        parts.append(f"trim ~{abs(b.delta_pct):.0f}% material around {axis_name}={b.lo:g}-{b.hi:g}")
    if thin:
        b = min(thin, key=lambda x: x.delta_pct)
        parts.append(f"add ~{abs(b.delta_pct):.0f}% material around {axis_name}={b.lo:g}-{b.hi:g}")
    if not dense:
        if missing_holes:
            x, y, z, r = missing_holes[0]
            parts.append(f"add {len(missing_holes)} hole(s) near ({x:g},{y:g},{z:g}) r≈{r:g}")
        if extra_holes:
            x, y, z, r = extra_holes[0]
            parts.append(f"remove {len(extra_holes)} hole(s) near ({x:g},{y:g},{z:g})")
        if resized_holes:
            x, y, z, gr, cr = resized_holes[0]
            verb = "shrink" if cr > gr else "enlarge"
            parts.append(f"{verb} {len(resized_holes)} hole(s) near ({x:g},{y:g},{z:g}) to r≈{gr:g}")
    elif holes_found != holes_expected:
        d = holes_expected - holes_found
        parts.append(f"{'add' if d > 0 else 'remove'} {abs(d)} hole(s) (dense field)")

    if not parts:
        # No flagged band / hole delta. Use the global volume / blob signal.
        if abs(vol_delta_pct) < 1.0 and extra_vol_pct < 1.5 and missing_vol_pct < 1.5:
            return "no correction needed (part matches reference within voxel tolerance)."
        if extra_vol_pct >= missing_vol_pct and extra_blob:
            return f"trim ~{extra_vol_pct:.0f}% excess material near {_fmt_pt(extra_blob)}."
        if missing_blob:
            return f"add ~{missing_vol_pct:.0f}% missing material near {_fmt_pt(missing_blob)}."
        return f"adjust volume by {vol_delta_pct:+.0f}% (no single dominant region)."
    return "; ".join(parts) + "."


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Regional 'where am I wrong' diff between a CAD candidate and a reference.")
    ap.add_argument("--cand", required=True, help="candidate .py / .step / .stl")
    ap.add_argument("--ref", required=True, help="reference task_id OR .step/.stl path")
    ap.add_argument("--pitch", type=float, default=None,
                    help="voxel pitch mm (default: max_extent/64 clamped 2-6)")
    ap.add_argument("--bands", type=int, default=12)
    ap.add_argument("--axis", default="auto", choices=["auto", "x", "y", "z"])
    ap.add_argument("--align", default="world", choices=["world", "pca"])
    ap.add_argument("--holes", default="section", choices=["section", "off"])
    ap.add_argument("--build-timeout", type=int, default=120)
    args = ap.parse_args(argv)

    cand_path = Path(args.cand)
    cand_mesh = _load_candidate_mesh(cand_path, build_timeout=args.build_timeout)
    ref_mesh = _load_reference_mesh(args.ref)

    cand_label = cand_path.name
    ref_label = Path(args.ref).name if Path(args.ref).exists() else args.ref

    rd = regiondiff(cand_mesh, ref_mesh, pitch=args.pitch, bands=args.bands,
                    axis=args.axis, align=args.align, holes=args.holes,
                    cand_label=cand_label, ref_label=ref_label)
    # The report uses box-drawing / math glyphs; Windows consoles default to cp1252
    # and choke on them. Reconfigure stdout to UTF-8 (Py3.7+) and fall back to an
    # ASCII transliteration if even that is unavailable.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rd.text)
    except Exception:
        ascii_map = {"─": "-", "Δ": "d", "→": "->", "≈": "~", "−": "-"}
        out = rd.text
        for k, v in ascii_map.items():
            out = out.replace(k, v)
        print(out.encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
