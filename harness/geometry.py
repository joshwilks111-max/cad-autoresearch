"""
geometry.py — low-level geometric comparison primitives.

Operates on trimesh.Trimesh objects (sampled from STL), with an optional B-rep
topology-signature path that uses OpenCASCADE (OCP) when a live build123d /
CadQuery solid is available. Mesh-first keeps the grader robust even when STEP
parsing is flaky: there is always an STL to fall back on.

Comparisons are scale-correct (we never silently normalise away a size error)
but pose-invariant where noted, because two CAD programs that produce the same
part may place it at a different origin / orientation.
"""
from __future__ import annotations

import numpy as np
import trimesh
from scipy.spatial import cKDTree


# --------------------------------------------------------------------------- #
#  Scalar metrics
# --------------------------------------------------------------------------- #
def volume(mesh: trimesh.Trimesh) -> float:
    """Absolute volume. Returns 0.0 for non-volumetric / invalid meshes."""
    try:
        v = float(abs(mesh.volume))
        return v if np.isfinite(v) else 0.0
    except Exception:
        return 0.0


def bbox_dims(mesh: trimesh.Trimesh) -> np.ndarray:
    """Bounding-box extents, SORTED ascending so the result is invariant to how
    the part happens to be oriented along the axes."""
    try:
        ext = mesh.bounding_box_oriented.primitive.extents
    except Exception:
        ext = mesh.extents
    ext = np.asarray(ext, dtype=float)
    ext = ext[np.isfinite(ext)]
    if ext.size == 0:
        return np.zeros(3)
    out = np.zeros(3)
    out[: ext.size] = np.sort(ext)
    return out


def relative_error(a: float, b: float) -> float:
    """Symmetric relative error in [0, inf). 0 == identical."""
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


# --------------------------------------------------------------------------- #
#  Sampling
# --------------------------------------------------------------------------- #
def sample_surface(mesh: trimesh.Trimesh, n: int, seed: int = 0) -> np.ndarray:
    """Deterministic surface sampling; falls back to vertices on failure.

    Determinism without poisoning global RNG: prefer trimesh's per-call ``seed=``
    kwarg (trimesh 4.x). If the installed signature predates it, fall back to a
    save/restore of NumPy's legacy global state so a parallel worker's RNG isn't
    left mutated after the call (the old code called ``np.random.seed`` and never
    restored it, corrupting concurrent workers' streams)."""
    if mesh is None or len(mesh.faces) == 0:
        return np.asarray(mesh.vertices if mesh is not None else np.zeros((1, 3)))
    rng = np.random.default_rng(seed)
    try:
        try:
            pts, _ = trimesh.sample.sample_surface(mesh, n, seed=seed)
        except TypeError:
            # Older trimesh: no seed kwarg. Seed the legacy global RNG but restore
            # it afterwards so we don't leak state into other workers.
            _state = np.random.get_state()
            try:
                np.random.seed(seed)
                pts, _ = trimesh.sample.sample_surface(mesh, n)
            finally:
                np.random.set_state(_state)
        return np.asarray(pts)
    except Exception:
        idx = rng.integers(0, len(mesh.vertices), size=min(n, len(mesh.vertices)))
        return np.asarray(mesh.vertices)[idx]


def sample_volume(mesh: trimesh.Trimesh, n: int, seed: int = 0) -> np.ndarray:
    """Sample points from the INTERIOR of a watertight mesh (for volumetric IoU).
    Falls back to surface sampling if the mesh isn't watertight or volume
    sampling underfills. Dense interior sampling is what makes the voxel IoU
    self-consistent: too few points and two samples of the SAME solid land in
    different voxels and the IoU collapses."""
    if mesh is None or len(mesh.faces) == 0:
        return np.zeros((0, 3))
    try:
        if mesh.is_watertight:
            # Seed locally + restore global state (see sample_surface rationale).
            _state = np.random.get_state()
            try:
                np.random.seed(seed)
                pts = trimesh.sample.volume_mesh(mesh, n)
            finally:
                np.random.set_state(_state)
            if len(pts) >= max(64, n // 4):
                return np.asarray(pts)
    except Exception:
        pass
    return sample_surface(mesh, n, seed)


# --------------------------------------------------------------------------- #
#  Chamfer distance
# --------------------------------------------------------------------------- #
def chamfer_distance(a: trimesh.Trimesh, b: trimesh.Trimesh,
                     n: int = 4000, seed: int = 0) -> float:
    """Symmetric Chamfer distance between two surfaces (mean of bidirectional
    nearest-neighbour distances). Both meshes are CENTRED first so this measures
    shape, not placement. Lower is better; 0 == identical surfaces. Units = mm."""
    pa = sample_surface(a, n, seed)
    pb = sample_surface(b, n, seed + 1)
    if len(pa) == 0 or len(pb) == 0:
        return float("inf")
    pa = pa - pa.mean(axis=0)
    pb = pb - pb.mean(axis=0)
    ta, tb = cKDTree(pa), cKDTree(pb)
    da, _ = tb.query(pa)
    db, _ = ta.query(pb)
    return float(0.5 * (np.mean(da) + np.mean(db)))


# --------------------------------------------------------------------------- #
#  Surface IoU (SIoU)
# --------------------------------------------------------------------------- #
def surface_iou(a: trimesh.Trimesh, b: trimesh.Trimesh,
                n: int = 4000, seed: int = 0,
                threshold_frac: float = 0.01) -> float:
    """Symmetric Surface IoU in [0, 1] — complementary to the volumetric IoU.

    Samples n points from each surface, then takes the F1 (harmonic mean) of two
    directed fractions: recall = fraction of candidate points within
    threshold_frac * gt_bbox_diagonal of the GT surface; precision = fraction of
    GT points within that distance of the candidate surface. Both directions must
    agree for a high score, so a phantom extra surface OR a missing surface both
    score low. Catches surface-shape errors (a flat face where a curved one
    belongs) that volume-identical solids hide from the volumetric IoU.

    Both clouds are CENTRED first (like chamfer_distance) so this measures shape,
    not placement — placement is already covered by IoU (PCA-aligned) + Chamfer.
    Deterministic: same sample_surface seed convention as chamfer_distance."""
    pa = sample_surface(a, n, seed)
    pb = sample_surface(b, n, seed + 1)
    if len(pa) == 0 or len(pb) == 0:
        return 0.0
    pa = pa - pa.mean(axis=0)
    pb = pb - pb.mean(axis=0)

    try:
        gt_ext = np.asarray(b.bounding_box_oriented.primitive.extents, dtype=float)
    except Exception:
        gt_ext = np.asarray(b.extents, dtype=float)
    gt_ext = gt_ext[np.isfinite(gt_ext)]
    diag = float(np.linalg.norm(gt_ext)) if gt_ext.size > 0 else 1.0
    if not np.isfinite(diag) or diag < 1e-9:
        diag = 1.0

    # Threshold = the real-error tolerance (frac of GT diagonal), but FLOORED to
    # clear the surface-sampling spacing. Two independent finite samplings of the
    # SAME surface have a nearest-neighbour distance ~= the sample spacing
    # (~sqrt(area / n)); if the tolerance is finer than that, even identical
    # surfaces fail it and self-SIoU collapses (the sampling floor that
    # deterministic voxelisation removed from the volumetric IoU). Floor at
    # ~1.5x the estimated spacing so self-SIoU -> ~1.0 while genuine surface
    # errors (which displace points by many spacings) are still penalised.
    try:
        gt_area = float(b.area)
    except Exception:
        gt_area = 0.0
    spacing = np.sqrt(gt_area / max(len(pb), 1)) if gt_area > 0 else 0.0
    thresh = max(threshold_frac * diag, 1.5 * spacing)

    tree_b = cKDTree(pb)
    da, _ = tree_b.query(pa)
    recall = float(np.mean(da <= thresh))      # do we cover the GT surface?

    tree_a = cKDTree(pa)
    db, _ = tree_a.query(pb)
    precision = float(np.mean(db <= thresh))   # no phantom surface?

    if recall + precision < 1e-9:
        return 0.0
    return float(2.0 * precision * recall / (precision + recall))


# --------------------------------------------------------------------------- #
#  Pose-invariant volumetric IoU
# --------------------------------------------------------------------------- #
def _canonical_frame(pts: np.ndarray) -> np.ndarray:
    """Centre on centroid and align principal axes to X/Y/Z via PCA. Axis signs
    are left ambiguous on purpose — the 48-transform search below resolves them,
    which is more robust than a skew heuristic on near-symmetric parts."""
    pts = pts - pts.mean(axis=0)
    cov = np.cov(pts.T)
    _, vecs = np.linalg.eigh(cov)          # ascending eigenvalues
    vecs = vecs[:, ::-1]                    # principal axis first
    return pts @ vecs


def _voxel_iou(pa: np.ndarray, pb: np.ndarray, res: int = 24) -> float:
    """Voxelise two point clouds on a shared grid; return occupancy IoU."""
    allpts = np.vstack([pa, pb])
    lo, hi = allpts.min(axis=0), allpts.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)

    def occ(p):
        idx = np.floor((p - lo) / span * (res - 1)).astype(int)
        idx = np.clip(idx, 0, res - 1)
        flat = idx[:, 0] * res * res + idx[:, 1] * res + idx[:, 2]
        g = np.zeros(res ** 3, dtype=bool)
        g[flat] = True
        return g

    ga, gb = occ(pa), occ(pb)
    inter = np.logical_and(ga, gb).sum()
    union = np.logical_or(ga, gb).sum()
    return float(inter / union) if union else 0.0


def _ortho_transforms() -> list[np.ndarray]:
    """All 48 axis-aligned orthogonal transforms: every axis permutation x every
    sign combination (det +/-1). Including reflections is deliberate — it stops a
    symmetric part scoring a false-low IoU when PCA assigns an arbitrary axis
    sign. Genuine chirality errors are caught by the topology / chamfer layers."""
    from itertools import permutations, product
    mats = []
    for perm in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for i, p in enumerate(perm):
                M[i, p] = signs[i]
            mats.append(M)
    return mats


def _voxel_centers(mesh: trimesh.Trimesh, res: int = 48) -> np.ndarray:
    """DETERMINISTIC interior occupancy as world-space voxel centres.

    Voxelise the (filled) solid on a grid whose pitch is the longest bbox extent
    divided by ``res``, and return the centres of all occupied cells. Unlike
    Monte-Carlo interior sampling, this is RNG-free and reproducible: the SAME
    mesh always yields the SAME centre set, so a self-comparison collapses to
    IoU == 1.0 instead of the ~0.975 sampling floor that random interior points
    produce. Returns an empty array on failure (caller falls back)."""
    try:
        ext = np.asarray(mesh.extents, dtype=float)
        ext = ext[np.isfinite(ext)]
        if ext.size == 0:
            return np.zeros((0, 3))
        pitch = float(np.max(ext)) / max(res, 1)
        if not np.isfinite(pitch) or pitch <= 0:
            return np.zeros((0, 3))
        vg = trimesh.voxel.creation.voxelize(mesh, pitch=pitch)
        # Fill the interior so we measure VOLUME occupancy, not just the shell.
        try:
            vg = vg.fill()
        except Exception:
            pass
        pts = np.asarray(vg.points, dtype=float)   # world-space occupied centres
        return pts if pts.ndim == 2 and len(pts) else np.zeros((0, 3))
    except Exception:
        return np.zeros((0, 3))


def iou(a: trimesh.Trimesh, b: trimesh.Trimesh,
        res: int = 24, n: int = 60000, seed: int = 0) -> float:
    """Rotation/translation-invariant VOLUMETRIC IoU in [0, 1].

    Derive DETERMINISTIC interior occupancy (filled-voxel centres) for both
    solids, bring each into a PCA canonical frame (centres + aligns principal
    axes by magnitude), then resolve the residual axis-sign/permutation ambiguity
    by trying all 48 signed orthogonal transforms on B and keeping the best
    occupancy IoU. Identical parts score EXACTLY 1.0 (no sampling floor); robust
    to placement, orientation, and symmetry-induced sign flips.

    Deterministic voxelisation (res*2 grid) replaces the old 60k Monte-Carlo
    interior sample, which capped self-IoU at ~0.975 and made high-fidelity
    attempts indistinguishable from sampling noise. Falls back to the legacy
    interior-sampling path if voxelisation fails (e.g. a non-watertight
    candidate), so a broken solid still scores rather than crashing."""
    pa = _voxel_centers(a, res=res * 2)
    pb = _voxel_centers(b, res=res * 2)
    if len(pa) == 0 or len(pb) == 0:
        # Voxelisation failed (likely non-watertight) — fall back to the old
        # Monte-Carlo interior sampling so the layer still produces a score.
        pa = sample_volume(a, n, seed)
        pb = sample_volume(b, n, seed + 7)
        if len(pa) == 0 or len(pb) == 0:
            return 0.0
    ca = _canonical_frame(pa)
    cb = _canonical_frame(pb)
    best = 0.0
    for R in _ortho_transforms():
        best = max(best, _voxel_iou(ca, cb @ R.T, res=res))
    return best


# --------------------------------------------------------------------------- #
#  Topology signature
# --------------------------------------------------------------------------- #
def topology_signature_from_solid(solid) -> dict | None:
    """B-rep counts (faces/edges/vertices/shells/solids) from a live build123d or
    CadQuery object. None if OCP isn't importable or the object can't unwrap."""
    try:
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX,
                                TopAbs_SHELL, TopAbs_SOLID)
    except Exception:
        return None
    wrapped = getattr(solid, "wrapped", solid)
    if wrapped is None:
        return None

    def count(kind):
        exp = TopExp_Explorer(wrapped, kind)
        seen = set()
        while exp.More():
            seen.add(exp.Current().__hash__())
            exp.Next()
        return len(seen)

    try:
        f = count(TopAbs_FACE)
        e = count(TopAbs_EDGE)
        v = count(TopAbs_VERTEX)
        return {
            "faces": f,
            "edges": e,
            "vertices": v,
            "shells": count(TopAbs_SHELL),
            "solids": count(TopAbs_SOLID),
            # Euler characteristic V - E + F. A missing through-hole shifts this by
            # 2, so it catches feature-count errors that the raw counts alone let
            # slip when only a subset of keys is compared (see EvoCAD, arXiv
            # 2510.11631: a part missing a required hole otherwise scores *better*
            # on IoU/Chamfer than one with a slightly-misplaced hole).
            "euler": v - e + f,
        }
    except Exception:
        return None


def topology_signature_from_mesh(mesh: trimesh.Trimesh) -> dict:
    """Cheap mesh-based topology proxy when no B-rep is available."""
    try:
        comps = mesh.body_count
    except Exception:
        comps = 1
    try:
        euler = int(mesh.euler_number)
    except Exception:
        euler = 0
    return {"components": int(comps), "euler": euler,
            "watertight": bool(mesh.is_watertight)}


def topology_match(sig_a: dict | None, sig_b: dict | None) -> float:
    """Weighted fraction of shared keys whose values match exactly. 0.5 (neutral)
    when one side has no signature at all.

    The Euler-characteristic key (``euler``) is weighted 2x when both signatures
    carry it: it is the single most diagnostic topology number (a missing/extra
    through-hole shifts it by 2), so a mismatch there should cost more than one
    of the five raw counts. Degrades gracefully — if ``euler`` is absent (e.g. a
    ground-truth ``topology.json`` written before this change), the weighting
    falls back to the original equal-weight fraction over the shared keys."""
    if not sig_a or not sig_b:
        return 0.5
    keys = set(sig_a) & set(sig_b)
    if not keys:
        return 0.5
    weight = {"euler": 2.0}
    total = sum(weight.get(k, 1.0) for k in keys)
    hits = sum(weight.get(k, 1.0) for k in keys if sig_a[k] == sig_b[k])
    return hits / total
