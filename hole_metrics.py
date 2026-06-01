"""
hole_metrics.py — through-hole / blind-hole discriminator (lane 3).

Counts holes in a mesh by cross-section loop analysis (shapely-free),
then classifies each as THROUGH or BLIND via bore-axis sampling with
mesh.contains().

Usage:
    python hole_metrics.py <mesh_or_candidate.py> [--json] [--sections 0.2,0.5,0.8]

Importable:
    from hole_metrics import hole_metrics
    result = hole_metrics(mesh)  # -> dict

Accuracy notes:
    - Reliable for cylindrical holes whose axis is aligned with one of the
      three principal axes (X, Y, Z), detected via Z, Y, X cross-sections.
    - Heuristic circularity threshold (r_std/r_mean < 0.15) may miss very
      coarse-meshed cylinders or catch rectangular notches on fine meshes.
    - Blind classification is definitive: if ANY sample point inside the
      bore is material (contains=True), the hole is BLIND.
    - Through classification can be fooled by very thin walls < sample_step.
    - Parts with angled/helical holes are NOT detected.
"""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
import os
from pathlib import Path
from typing import Sequence

import numpy as np
import trimesh


# ---------------------------------------------------------------------------
# Core metric
# ---------------------------------------------------------------------------

def _circularity(pts_2d: np.ndarray) -> tuple[float, float, float]:
    """Return (centroid_x, centroid_y, radius_mean) for a loop; also check."""
    ctr = pts_2d.mean(axis=0)
    radii = np.linalg.norm(pts_2d - ctr, axis=1)
    return ctr, radii.mean(), radii.std()


def _loops_at_height(mesh: trimesh.Trimesh, origin: np.ndarray,
                     normal: np.ndarray) -> list[dict]:
    """
    Section the mesh at a plane and return loop info dicts.
    Uses only mesh.section() + entities/vertices (NO shapely).
    """
    sec = mesh.section(plane_origin=origin, plane_normal=normal)
    if sec is None:
        return []
    V = np.asarray(sec.vertices)  # shape (N, 3)
    loops = []
    for entity in sec.entities:
        pts3d = V[entity.points]          # (k, 3)
        # Project to 2D in the plane by dropping the dominant axis
        ax = int(np.argmax(np.abs(normal)))  # 0=X,1=Y,2=Z
        keep = [i for i in range(3) if i != ax]
        pts2d = pts3d[:, keep]
        if len(pts2d) < 5:
            continue
        ctr, r_mean, r_std = _circularity(pts2d)
        if r_mean < 0.5:
            continue  # degenerate
        loops.append({
            "ctr2d": ctr,
            "r_mean": float(r_mean),
            "r_std": float(r_std),
            "n_pts": len(pts2d),
        })
    return loops


def _is_through(mesh: trimesh.Trimesh, center3d: np.ndarray,
                axis: np.ndarray, radius: float,
                n_samples: int = 20) -> bool:
    """
    Return True if the bore at center3d along axis is THROUGH.
    Samples n_samples points along the axis span of the mesh and
    checks that none of them are inside the mesh (i.e. all air).
    We sample at r=0 (bore center) over the full mesh thickness.
    """
    # Find extent of mesh along the bore axis
    dots = mesh.vertices @ axis
    t_min, t_max = dots.min(), dots.max()
    thickness = t_max - t_min
    if thickness < 0.5:
        return False  # degenerate

    # Build sample points along the bore axis
    ts = np.linspace(t_min + 0.05 * thickness, t_max - 0.05 * thickness, n_samples)
    # Each sample: project center onto axis then move to that t
    # center3d_proj = center3d - (center3d @ axis - t_start) * axis ... easier:
    # The bore center at parameter t is: center_on_axis(t) = axis_origin + t * axis
    # where axis_origin is on the axis passing through center3d.
    # center3d minus its projection onto axis:
    center_perp = center3d - (center3d @ axis) * axis
    sample_pts = np.array([center_perp + t * axis for t in ts])

    inside = mesh.contains(sample_pts)
    # THROUGH: all sample points are air (not inside material)
    return bool(not inside.any())


def _auto_fracs(span: float, step_mm: float = 4.0,
                max_planes: int = 13) -> list[float]:
    """Dense evenly-spaced section fractions (5%..95%) along an axis. ~`step_mm`
    spacing, clamped to [3, max_planes] planes. Replaces the naive {0.2,0.5,0.8}
    placement that MISSES a thin feature: an 8mm base in a 44mm-tall part has NO
    plane through it at fractions of the full 44mm; ~4mm spacing slices it."""
    if span < 0.5:
        return []
    n = int(np.clip(round(span / step_mm), 3, max_planes))
    return list(np.linspace(0.05, 0.95, n))


def _detect_holes_for_axis(mesh: trimesh.Trimesh, axis_idx: int,
                            section_fracs: Sequence[float] | None,
                            circ_threshold: float = 0.15) -> list[dict]:
    """
    Detect hole candidates by sectioning perpendicular to axis_idx (0=X,1=Y,2=Z).
    Returns a list of candidate hole dicts keyed by (center, radius).

    section_fracs=None -> dense auto-placement (every ~4mm), so a hole in a thin
    feature anywhere along the axis is sliced. An explicit sequence overrides it.
    """
    normal = np.zeros(3)
    normal[axis_idx] = 1.0

    bounds_min = mesh.bounds[0]
    bounds_max = mesh.bounds[1]
    span = bounds_max[axis_idx] - bounds_min[axis_idx]
    if span < 0.5:
        return []

    fracs = _auto_fracs(span) if section_fracs is None else list(section_fracs)

    # Collect candidate holes across sections; deduplicate by proximity
    candidates: dict[tuple, dict] = {}  # key=(rounded center3d, axis_idx)

    for frac in fracs:
        pos = bounds_min[axis_idx] + frac * span
        origin = mesh.centroid.copy()
        origin[axis_idx] = pos

        loops = _loops_at_height(mesh, origin, normal)
        if not loops:
            continue

        # Sort loops by radius: smallest loops first (inner = candidate holes)
        loops_sorted = sorted(loops, key=lambda l: l["r_mean"])
        if len(loops_sorted) < 2:
            # Only one loop: could be a solid cross section without holes
            continue

        # Inner loops (all but the outermost) are hole candidates
        outer_r = loops_sorted[-1]["r_mean"]
        for loop in loops_sorted[:-1]:
            r = loop["r_mean"]
            r_std = loop["r_std"]

            # Circularity check
            if r_std > circ_threshold * r:
                continue  # not circular
            # Skip loops that are nearly as large as the outer (probably outer error)
            if r > 0.85 * outer_r:
                continue

            ctr2d = loop["ctr2d"]
            # Reconstruct 3D center: axis coord = section origin; other two = ctr2d
            center3d = np.zeros(3)
            keep = [i for i in range(3) if i != axis_idx]
            center3d[axis_idx] = pos
            center3d[keep[0]] = ctr2d[0]
            center3d[keep[1]] = ctr2d[1]

            # Dedup: same hole at multiple section fracs — key only on
            # the PERPENDICULAR coords (the axis coord changes per section)
            keep = [i for i in range(3) if i != axis_idx]
            key = (axis_idx,
                   round(center3d[keep[0]], 0),
                   round(center3d[keep[1]], 0))
            if key in candidates:
                # Keep the one with the tightest circularity
                if r_std < candidates[key]["r_std"]:
                    candidates[key] = {
                        "center3d": center3d,
                        "r_mean": r,
                        "r_std": r_std,
                        "axis_idx": axis_idx,
                    }
            else:
                candidates[key] = {
                    "center3d": center3d,
                    "r_mean": r,
                    "r_std": r_std,
                    "axis_idx": axis_idx,
                }

    return list(candidates.values())


def hole_metrics(mesh: trimesh.Trimesh,
                 section_fracs: Sequence[float] | None = None,
                 circ_threshold: float = 0.15) -> dict:
    """
    Analyse a mesh for through and blind holes.

    Parameters
    ----------
    mesh : trimesh.Trimesh
    section_fracs : fractions of the bounding box at which to section. DEFAULT None =
        dense auto-placement (~every 4mm per axis), which catches holes in a thin
        feature (e.g. an 8mm base of a 44mm-tall part) that the old fixed {0.2,0.5,0.8}
        missed entirely. Pass an explicit sequence to override.
    circ_threshold : r_std/r_mean threshold for accepting a loop as circular

    Returns
    -------
    dict with keys: n_holes, n_through, n_blind, holes (list of dicts)
    """
    all_candidates: list[dict] = []

    # Search along all three principal axes (section_fracs=None -> dense per-axis)
    for ax in range(3):
        cands = _detect_holes_for_axis(mesh, ax, section_fracs, circ_threshold)
        all_candidates.extend(cands)

    # Deduplicate across axes: if two candidates have centers within r/2 of each other
    # and the same radius (within 20%), keep one
    merged: list[dict] = []
    for cand in all_candidates:
        c = cand["center3d"]
        r = cand["r_mean"]
        duplicate = False
        for kept in merged:
            dist = np.linalg.norm(c - kept["center3d"])
            if dist < 0.5 * min(r, kept["r_mean"]) and abs(r - kept["r_mean"]) < 0.2 * r:
                duplicate = True
                break
        if not duplicate:
            merged.append(cand)

    # Classify each candidate as through or blind
    axis_names = ["X", "Y", "Z"]
    holes = []
    for cand in merged:
        ax_idx = cand["axis_idx"]
        axis = np.zeros(3)
        axis[ax_idx] = 1.0
        center3d = cand["center3d"]
        radius = cand["r_mean"]

        through = _is_through(mesh, center3d, axis, radius)
        kind = "through" if through else "blind"

        holes.append({
            "center": center3d.tolist(),
            "radius": float(round(radius, 3)),
            "axis": axis_names[ax_idx],
            "kind": kind,
            "r_std": float(round(cand["r_std"], 4)),
        })

    n_through = sum(1 for h in holes if h["kind"] == "through")
    n_blind = sum(1 for h in holes if h["kind"] == "blind")

    return {
        "n_holes": len(holes),
        "n_through": n_through,
        "n_blind": n_blind,
        "holes": holes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_mesh(path: str) -> trimesh.Trimesh:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"not found: {path}")

    if p.suffix.lower() == ".py":
        # Run the candidate in a unique temp workspace
        import sys as _sys
        repo_root = Path(__file__).parent
        _sys.path.insert(0, str(repo_root))
        from harness.runner import run_candidate
        code = p.read_text(encoding="utf-8")
        ws = Path(tempfile.mkdtemp(prefix="_lane3_"))
        rr = run_candidate(code, ws)
        if not rr.ok:
            raise RuntimeError(f"candidate failed: {rr.error}\n{rr.stderr}")
        return rr.mesh

    if p.suffix.lower() in (".step", ".stp"):
        # trimesh has NO OCC backend -> trimesh.load("x.step") silently fails. STEP must
        # go through build123d's kernel import, then tessellate (same as regiondiff /
        # timetrial.grade_step). Tolerance 0.05 matches the harness sandbox export.
        from build123d import import_step, export_stl
        solid = import_step(str(p))
        out = Path(tempfile.mkdtemp(prefix="_lane3_step_")) / "in.stl"
        export_stl(solid, str(out), tolerance=0.05)
        return trimesh.load(str(out), force="mesh")

    # STL, OBJ, PLY, etc. — formats trimesh parses natively.
    return trimesh.load(str(p), force="mesh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hole metrics for a CAD mesh")
    parser.add_argument("mesh", help="Path to .stl/.step or candidate .py file")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--sections",
        default=None,
        help="Comma-separated section fractions (default: dense auto-placement ~every 4mm). "
             "Pass e.g. 0.2,0.5,0.8 to override.",
    )
    args = parser.parse_args()

    fracs = [float(x) for x in args.sections.split(",")] if args.sections else None
    mesh = _load_mesh(args.mesh)
    result = hole_metrics(mesh, section_fracs=fracs)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"n_holes={result['n_holes']}  n_through={result['n_through']}  n_blind={result['n_blind']}")
        for h in result["holes"]:
            print(
                f"  {h['kind'].upper():7s}  axis={h['axis']}  "
                f"r={h['radius']:.2f}mm  "
                f"center=({h['center'][0]:.1f},{h['center'][1]:.1f},{h['center'][2]:.1f})  "
                f"r_std={h['r_std']:.4f}"
            )


if __name__ == "__main__":
    main()
