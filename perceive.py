"""
perceive.py — give a blind agent perception of candidate vs reference.

Two complementary outputs:
  (a) ASCII silhouette diff  — works in any text-only terminal / agent context
      (~600 chars per view, in-band, no files needed)
  (b) overlay PNG            — rich for VLM agents; GT (gray) + candidate
      (colored by signed distance) superimposed in one figure

Usage (CLI):
    python perceive.py --cand tasks/bearing_608/best_candidate.py --ref bearing_608 --ascii
    python perceive.py --cand tasks/bearing_608/best_candidate.py --ref bearing_608 --png
    python perceive.py --cand tasks/bearing_608/best_candidate.py --ref bearing_608 --both

Importable API:
    ascii_diff(cand_mesh, ref_mesh, view="front", grid=(64,32)) -> str
    overlay_png(cand_mesh, ref_mesh, out_dir, views=("front","top","right")) -> list[str]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # headless — must precede pyplot import
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np               # noqa: E402
import trimesh                   # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

REPO = Path(__file__).resolve().parent

# Elevation / azimuth that match render.py's _VIEWS dict
_VIEW_ANGLES = {
    "front": (0, -90),
    "top":   (90, -90),
    "right": (0, 0),
    "iso":   (28, 45),
}

# Axis to DROP for 2-D projection (projects the remaining two axes onto a plane)
# front=XZ plane (drop Y), top=XY plane (drop Z), right=YZ plane (drop X)
_DROP_AXIS = {"front": 1, "top": 2, "right": 0, "iso": None}


# ---------------------------------------------------------------------------
#  Mesh helpers
# ---------------------------------------------------------------------------

def _load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a STEP or STL mesh by file path."""
    path = Path(path)
    mesh = trimesh.load(str(path), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    return mesh


def _run_candidate_mesh(py_path: str | Path) -> trimesh.Trimesh:
    """Execute a .py candidate in a unique temp workspace and return its mesh."""
    from harness.runner import run_candidate  # local import — avoids circular at module level

    py_path = Path(py_path)
    code = py_path.read_text(encoding="utf-8")
    ws = tempfile.mkdtemp(prefix=f"_perceive_{os.getpid()}_")
    result = run_candidate(code, workspace=ws, python=sys.executable)
    if not result.ok or result.mesh is None:
        raise RuntimeError(
            f"perceive: candidate execution failed — {result.error}\n"
            f"stderr: {result.stderr[-800:]}"
        )
    return result.mesh


def _resolve_cand(cand: str | Path) -> trimesh.Trimesh:
    """Resolve a candidate path: .py → run it; .step/.stl → load directly."""
    cand = Path(cand)
    suffix = cand.suffix.lower()
    if suffix == ".py":
        return _run_candidate_mesh(cand)
    if suffix in (".step", ".stp", ".stl"):
        return _load_mesh(cand)
    raise ValueError(f"perceive: unknown candidate extension '{suffix}'")


def _resolve_ref(ref: str) -> trimesh.Trimesh:
    """Resolve a reference: task_id string → load GT STL; file path → load it."""
    p = Path(ref)
    if p.exists():
        return _load_mesh(p)
    # treat as task_id
    gt_stl = REPO / "tasks" / ref / "ground_truth" / "result.stl"
    if not gt_stl.exists():
        raise FileNotFoundError(
            f"perceive: ground truth STL not found for task '{ref}'.\n"
            f"Expected: {gt_stl}\n"
            f"Build it with: python tasks/{ref}/make_ground_truth.py"
        )
    return trimesh.load(str(gt_stl), force="mesh")


# ---------------------------------------------------------------------------
#  (a) ASCII silhouette diff
# ---------------------------------------------------------------------------

def _project_2d(mesh: trimesh.Trimesh, drop: int) -> np.ndarray:
    """Return (N,2) 2-D surface point cloud by dropping one coordinate axis."""
    pts = np.asarray(mesh.vertices, dtype=float)
    axes = [i for i in range(3) if i != drop]
    return pts[:, axes]


def _rasterize(pts2d: np.ndarray, grid_w: int, grid_h: int,
               lo: np.ndarray, span: np.ndarray) -> np.ndarray:
    """
    Rasterize 2-D points to a boolean mask of shape (grid_h, grid_w).
    lo/span define the shared bounding box for both meshes.
    """
    if len(pts2d) == 0:
        return np.zeros((grid_h, grid_w), dtype=bool)
    cx = np.clip(((pts2d[:, 0] - lo[0]) / span[0] * (grid_w - 1)).astype(int), 0, grid_w - 1)
    cy = np.clip(((pts2d[:, 1] - lo[1]) / span[1] * (grid_h - 1)).astype(int), 0, grid_h - 1)
    mask = np.zeros((grid_h, grid_w), dtype=bool)
    mask[cy, cx] = True
    return mask


def _iou_2d(ma: np.ndarray, mb: np.ndarray) -> float:
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    return float(inter / union) if union else 0.0


def ascii_diff(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
               view: str = "front", grid: tuple[int, int] = (64, 32)) -> str:
    """
    Return an ASCII silhouette diff string comparing cand_mesh to ref_mesh.

    Symbols:
      # = both present
      + = candidate-only (too fat / extra material)
      · = GT-only (missing material)
      (space) = neither

    Parameters
    ----------
    view  : "front" | "top" | "right" | "iso" | "all"
            If "all", returns all three orthographic views concatenated.
    grid  : (width, height) in characters
    """
    if view == "all":
        views = ["front", "top", "right"]
        parts = [ascii_diff(cand_mesh, ref_mesh, v, grid) for v in views]
        return "\n\n".join(parts)

    grid_w, grid_h = grid
    drop = _DROP_AXIS.get(view)
    if drop is None:
        # iso — use front as fallback
        drop = _DROP_AXIS["front"]

    pc = _project_2d(cand_mesh, drop)
    pg = _project_2d(ref_mesh, drop)

    # Shared bounding box
    all_pts = np.vstack([pc, pg])
    lo = all_pts.min(axis=0)
    hi = all_pts.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)

    mc = _rasterize(pc, grid_w, grid_h, lo, span)
    mg = _rasterize(pg, grid_w, grid_h, lo, span)

    iou2d = _iou_2d(mc, mg)

    # Build char grid (row 0 = top visually → flip vertically)
    lines = []
    for row in range(grid_h - 1, -1, -1):
        line = []
        for col in range(grid_w):
            c_on = mc[row, col]
            g_on = mg[row, col]
            if c_on and g_on:
                line.append("#")
            elif c_on:
                line.append("+")
            elif g_on:
                line.append("·")   # middle dot ·
            else:
                line.append(" ")
        lines.append("".join(line))

    # Trim leading/trailing blank lines
    first = next((i for i, l in enumerate(lines) if l.strip()), 0)
    last = next((i for i, l in enumerate(reversed(lines)) if l.strip()), 0)
    lines = lines[first: len(lines) - last]

    # Header
    view_name = view.upper()
    header = (
        f"PERCEIVE  view={view_name}   grid={grid_w}x{grid_h}   2D-IoU={iou2d:.2f}\n"
        f"  # both   + cand-only   · GT-only\n"
    )
    body = "\n".join(lines)
    footer = f"\n2D silhouette IoU  {view} {iou2d:.2f}"
    return header + body + footer


def ascii_diff_all_views(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
                         grid: tuple[int, int] = (64, 32)) -> str:
    """
    Run ascii_diff for front/top/right and append a summary line
    indicating the lowest-IoU view.
    """
    views = ["front", "top", "right"]
    grid_w, grid_h = grid
    drop_map = {"front": 1, "top": 2, "right": 0}

    ious = {}
    blocks = {}
    for v in views:
        drop = drop_map[v]
        pc = _project_2d(cand_mesh, drop)
        pg = _project_2d(ref_mesh, drop)
        all_pts = np.vstack([pc, pg])
        lo = all_pts.min(axis=0)
        hi = all_pts.max(axis=0)
        span = np.maximum(hi - lo, 1e-6)
        mc = _rasterize(pc, grid_w, grid_h, lo, span)
        mg = _rasterize(pg, grid_w, grid_h, lo, span)
        ious[v] = _iou_2d(mc, mg)

        # Build the block for this view (same logic as ascii_diff)
        lines = []
        for row in range(grid_h - 1, -1, -1):
            line = []
            for col in range(grid_w):
                c_on = mc[row, col]
                g_on = mg[row, col]
                if c_on and g_on:
                    line.append("#")
                elif c_on:
                    line.append("+")
                elif g_on:
                    line.append("·")
                else:
                    line.append(" ")
            lines.append("".join(line))
        first = next((i for i, l in enumerate(lines) if l.strip()), 0)
        last_i = next((i for i, l in enumerate(reversed(lines)) if l.strip()), 0)
        lines = lines[first: len(lines) - last_i]
        header = (
            f"PERCEIVE  view={v.upper()}   grid={grid_w}x{grid_h}   2D-IoU={ious[v]:.2f}\n"
            f"  # both   + cand-only   · GT-only\n"
        )
        blocks[v] = header + "\n".join(lines)

    worst_v = min(ious, key=lambda k: ious[k])
    iou_line = "2D silhouette IoU  " + "  ".join(f"{v} {ious[v]:.2f}" for v in views)
    iou_line += f"   (lowest: {worst_v} — look there)"

    return "\n\n".join(blocks[v] for v in views) + "\n\n" + iou_line


# ---------------------------------------------------------------------------
#  (b) Overlay PNG
# ---------------------------------------------------------------------------

def _signed_dist(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
                 n_pts: int = 8000) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (pts, signed_dist) for candidate surface points.
    Positive = candidate surface is OUTSIDE (protruding) the GT.
    Negative = candidate surface is INSIDE / recessed from GT.
    Uses cKDTree nearest-neighbor distance; sign derived from
    mesh's face normals (inside vs outside GT).
    """
    from harness.geometry import sample_surface

    pts_c = sample_surface(cand_mesh, n_pts, seed=0)
    pts_g = sample_surface(ref_mesh, n_pts, seed=1)

    if len(pts_g) == 0:
        return pts_c, np.zeros(len(pts_c))

    tree = cKDTree(pts_g)
    dists, idxs = tree.query(pts_c)

    # Approximate sign: a candidate point is "outside" the GT when the vector
    # from the nearest GT surface point points in the SAME direction as the GT
    # face normal at that point (dot > 0 → outside; < 0 → inside).
    try:
        gt_normals = ref_mesh.face_normals          # per-face
        gt_face_centers = ref_mesh.triangles_center  # per-face centroid
        # Nearest face for each candidate surface point
        tree_fc = cKDTree(gt_face_centers)
        _, fi = tree_fc.query(pts_c)
        normals_at_nearest = gt_normals[fi]
        vecs = pts_c - gt_face_centers[fi]
        signs = np.sign(np.einsum("ij,ij->i", vecs, normals_at_nearest))
        signs[signs == 0] = 1.0
    except Exception:
        signs = np.ones(len(pts_c))

    return pts_c, dists * signs


def _decimate_if_needed(mesh: trimesh.Trimesh, max_faces: int = 20_000) -> trimesh.Trimesh:
    """Reduce triangle count if above max_faces to keep rendering fast."""
    if len(mesh.faces) > max_faces:
        try:
            mesh = mesh.simplify_quadric_decimation(max_faces)
        except Exception:
            pass  # if simplification fails, keep original
    return mesh


def overlay_png(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
                out_dir: str | Path,
                views: tuple[str, ...] = ("front", "top", "right")) -> list[str]:
    """
    Render an overlay PNG for each requested view.

    GT is drawn as a low-alpha gray solid; candidate is colored by signed
    distance to GT surface (red = protruding/extra, blue = recessed/missing,
    near-white/gray = correct).

    Returns a list of written file paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Decimate large meshes for speed
    cand_d = _decimate_if_needed(cand_mesh)
    ref_d = _decimate_if_needed(ref_mesh)

    # Compute signed distance coloring for candidate surface
    try:
        pts_c, sdist = _signed_dist(cand_mesh, ref_mesh)
        has_sdist = True
    except Exception:
        has_sdist = False

    n_views = len(views)
    paths = []

    for view in views:
        elev, azim = _VIEW_ANGLES.get(view, (0, -90))
        fig = plt.figure(figsize=(5, 5))
        ax = fig.add_subplot(1, 1, 1, projection="3d")
        ax.view_init(elev=elev, azim=azim)

        # --- Draw GT as low-alpha gray background ---
        vg, fg = ref_d.vertices, ref_d.faces
        if len(fg) > 0:
            ax.plot_trisurf(
                vg[:, 0], vg[:, 1], vg[:, 2], triangles=fg,
                color=(0.7, 0.7, 0.7), alpha=0.25,
                linewidth=0, antialiased=False, shade=False,
                label="GT"
            )

        # --- Draw candidate colored by signed distance ---
        vc, fc = cand_d.vertices, cand_d.faces
        if len(fc) > 0:
            if has_sdist and len(sdist) > 0:
                # Map per-vertex sdist from nearest sample point
                try:
                    tree_s = cKDTree(pts_c)
                    _, vi = tree_s.query(vc)
                    vi = np.clip(vi, 0, len(sdist) - 1)
                    sdist_v = sdist[vi]
                    # Normalize: clip at ±5% of GT diagonal for contrast
                    try:
                        gt_diag = float(np.linalg.norm(ref_mesh.extents))
                    except Exception:
                        gt_diag = 1.0
                    clip_val = max(gt_diag * 0.05, 1e-3)
                    norm_d = np.clip(sdist_v / clip_val, -1.0, 1.0)
                    # -1 → blue (missing), 0 → white, +1 → red (extra)
                    r = np.clip(0.5 + 0.5 * norm_d, 0, 1)
                    g_ch = np.clip(0.5 - 0.4 * np.abs(norm_d), 0, 1)
                    b = np.clip(0.5 - 0.5 * norm_d, 0, 1)
                    face_colors = np.column_stack([
                        (r[fc[:, 0]] + r[fc[:, 1]] + r[fc[:, 2]]) / 3,
                        (g_ch[fc[:, 0]] + g_ch[fc[:, 1]] + g_ch[fc[:, 2]]) / 3,
                        (b[fc[:, 0]] + b[fc[:, 1]] + b[fc[:, 2]]) / 3,
                        np.full(len(fc), 0.85),
                    ])
                    ax.plot_trisurf(
                        vc[:, 0], vc[:, 1], vc[:, 2], triangles=fc,
                        facecolors=face_colors,
                        linewidth=0, antialiased=True, shade=True,
                        label="Candidate"
                    )
                except Exception:
                    # Fall back to solid color if coloring fails
                    ax.plot_trisurf(
                        vc[:, 0], vc[:, 1], vc[:, 2], triangles=fc,
                        color=(0.3, 0.5, 0.8), alpha=0.85,
                        linewidth=0, antialiased=True, shade=True,
                        label="Candidate"
                    )
            else:
                ax.plot_trisurf(
                    vc[:, 0], vc[:, 1], vc[:, 2], triangles=fc,
                    color=(0.3, 0.5, 0.8), alpha=0.85,
                    linewidth=0, antialiased=True, shade=True,
                    label="Candidate"
                )

        # Set limits to include both meshes
        all_verts = np.vstack([vc, vg]) if len(vg) > 0 and len(vc) > 0 else (vc if len(vc) > 0 else vg)
        if len(all_verts) > 0:
            c = all_verts.mean(axis=0)
            r = float(np.max(np.abs(all_verts - c))) or 1.0
            ax.set_xlim(c[0] - r, c[0] + r)
            ax.set_ylim(c[1] - r, c[1] + r)
            ax.set_zlim(c[2] - r, c[2] + r)
            ax.set_box_aspect((1, 1, 1))

        ax.set_title(f"overlay · {view}\n(gray=GT  red=extra  blue=missing)", fontsize=8)
        ax.set_axis_off()

        out_path = out_dir / f"overlay_{view}.png"
        fig.tight_layout()
        fig.savefig(str(out_path), dpi=90)
        plt.close(fig)
        paths.append(str(out_path))

    return paths


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """GT-free self-test: build the bearing in-memory (via its GENERATOR script,
    not its ground_truth/), export to a scratch STL, and ASCII-diff the part against
    ITSELF. A part vs itself must be overlap-dominated (mostly '#', no '+'/'.'),
    2D-IoU ~1.0 in every view. Never reads any ground_truth/ file."""
    import importlib.util
    print("=" * 60)
    print("perceive.py self-test (GT-free: bearing vs itself)")
    print("=" * 60)

    # Build the bearing from its generator (the authoring path, not the GT geometry).
    here = Path(__file__).resolve().parent
    gen = here / "tasks" / "bearing_608" / "make_ground_truth.py"
    spec = importlib.util.spec_from_file_location("bearing_gen", str(gen))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    solid = mod.build()

    from build123d import export_stl
    ws = Path(tempfile.mkdtemp(prefix="perceive_selftest_"))
    stl = ws / "bearing.stl"
    export_stl(solid, str(stl), tolerance=0.05)

    mesh = _load_mesh(stl)
    n_pass = n_fail = 0
    # A part vs itself must be overlap-DOMINATED. At a finite 64x32 raster, a single
    # silhouette-edge cell can land on a bin boundary and shimmer to one '+' + one
    # '.' — that's rasterization noise, not misalignment. The honest bar: lots of
    # '#', divergence <= 2 cells per view (and the tool's own 2D-IoU == 1.00).
    DIVERGENCE_TOL = 2
    for view in ("front", "top", "right"):
        txt = ascii_diff(mesh, mesh, view=view, grid=(64, 32))
        n_both = txt.count("#")
        n_extra = txt.count("+")
        n_missing = txt.count("·")  # middle dot
        ok = (n_both > 0) and (n_extra <= DIVERGENCE_TOL) and (n_missing <= DIVERGENCE_TOL)
        if ok:
            n_pass += 1
            print(f"  [PASS] {view:5s}  #={n_both:4d}  +={n_extra}  dot={n_missing} "
                  f"(<= {DIVERGENCE_TOL} edge-shimmer cells)")
        else:
            n_fail += 1
            print(f"  [FAIL] {view:5s}  #={n_both}  +={n_extra}  dot={n_missing} "
                  f"(self-diff divergence exceeds {DIVERGENCE_TOL} cells)")

    # Also exercise the importable overlay_png path (render without error).
    try:
        paths = overlay_png(mesh, mesh, ws, views=("front",))
        png_ok = len(paths) == 1 and Path(paths[0]).stat().st_size > 0
        n_pass += int(png_ok); n_fail += int(not png_ok)
        print(f"  [{'PASS' if png_ok else 'FAIL'}] overlay_png rendered "
              f"({Path(paths[0]).stat().st_size // 1024} KB)" if png_ok
              else "  [FAIL] overlay_png produced no file")
    except Exception as e:  # noqa: BLE001
        n_fail += 1
        print(f"  [FAIL] overlay_png raised: {e!r}")

    print("=" * 60)
    print(f"Results: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 60)
    if n_fail:
        print("SELF-TEST FAILED")
        return 1
    print("ALL PERCEIVE SELF-TESTS PASSED")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="perceive.py — ASCII silhouette diff + overlay PNG of candidate vs GT"
    )
    ap.add_argument("--cand",
                    help=".py source, .step, or .stl path for the candidate")
    ap.add_argument("--ref",
                    help="task_id (e.g. bearing_608) or path to a reference .stl/.step")
    ap.add_argument("--ascii", action="store_true", help="produce ASCII silhouette diff")
    ap.add_argument("--png", action="store_true", help="produce overlay PNG(s)")
    ap.add_argument("--both", action="store_true", help="produce both ASCII and PNG")
    ap.add_argument("--view", default="all",
                    choices=["front", "top", "right", "iso", "all"],
                    help="which view(s) to render (default: all three orthographic)")
    ap.add_argument("--grid", default="64x32",
                    help="ASCII raster size WxH (default: 64x32)")
    ap.add_argument("--out", default=None,
                    help="output directory for PNGs (default: runs/_perceive_<pid>)")
    ap.add_argument("--selftest", action="store_true",
                    help="GT-free self-test: bearing-vs-itself ASCII diff (no task GT read)")
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(_selftest())
    if not args.cand or not args.ref:
        ap.error("--cand and --ref are required (unless --selftest)")

    # Parse grid
    try:
        gw, gh = [int(x) for x in args.grid.lower().split("x")]
    except Exception:
        ap.error("--grid must be WxH, e.g. 64x32")

    do_ascii = args.ascii or args.both or (not args.png)
    do_png = args.png or args.both

    # Resolve meshes
    print(f"[perceive] loading candidate: {args.cand}", flush=True)
    cand_mesh = _resolve_cand(args.cand)
    print(f"[perceive] loading reference: {args.ref}", flush=True)
    ref_mesh = _resolve_ref(args.ref)
    print(
        f"[perceive] cand faces={len(cand_mesh.faces)}  "
        f"ref faces={len(ref_mesh.faces)}",
        flush=True
    )

    # ASCII output
    if do_ascii:
        views = ["front", "top", "right"] if args.view == "all" else [args.view]
        if args.view == "all":
            result = ascii_diff_all_views(cand_mesh, ref_mesh, grid=(gw, gh))
        else:
            result = ascii_diff(cand_mesh, ref_mesh, view=args.view, grid=(gw, gh))
        print(result)

    # PNG output
    if do_png:
        out_dir = args.out or (REPO / "runs" / f"_perceive_{os.getpid()}")
        views = (
            ("front", "top", "right") if args.view == "all"
            else ("front", "top", "right", "iso") if args.view == "iso"
            else (args.view,)
        )
        paths = overlay_png(cand_mesh, ref_mesh, out_dir, views=views)
        for p in paths:
            sz = Path(p).stat().st_size
            print(f"[perceive] PNG written: {p}  ({sz // 1024} KB)")


if __name__ == "__main__":
    main()
