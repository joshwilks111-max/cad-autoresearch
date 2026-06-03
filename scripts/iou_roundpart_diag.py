#!/usr/bin/env python3
"""
iou_roundpart_diag.py — DIAGNOSTIC (read-only) for the round-part IoU degeneracy.

Issue #7 / known-limitations.md §2: a correct round part can score a degraded IoU
against an equivalent build of the SAME solid, because the cylindrical-IoU radial
frame is quantization-sensitive. This script MEASURES the mechanism (it does NOT
touch guarded harness/geometry.py). It is GT-free: builds bearing_608 from public
standard dimensions, never reads tasks/bearing_608/ground_truth/. It calls the REAL
harness functions (not re-implementations) so the diagnosis reflects production.

============================================================================
FINDING (2026-06-03, CORRECTED after /review adversarial pass): BUG IS REAL.
============================================================================
An earlier version of this script built bearing_608 two ways (`Circle-Circle
extrude` vs `Cylinder-Cylinder`) and concluded "does not reproduce" — WRONG. Those
two primitives happen to lower to BYTE-IDENTICAL meshes (both 504 verts), so they
never created the "two DIFFERENT meshes of the same solid" condition the bug needs.
Building the SAME round annulus a third way (`Ellipse(11,11)` — a circle expressed
as an ellipse, still perfectly round) produces a DIFFERENT tessellation (530 verts),
and the bug reproduces through the real grader:

    iou(circle-annulus, ellipse-annulus) = 0.7826   (deterministic, 5/5 repeats)
    self-IoU = 1.0000 for each
    both rotationally-symmetric -> both routed to _cylindrical_iou
    in-plane eigenvalue ratio = 1.0 (genuinely round, NOT eccentric)

ROOT CAUSE (measured, not assumed): the radial frame `rmax = max(ra.max(), rb.max())`
at harness/geometry.py:259 is derived from the SAMPLED point clouds. A sub-micron
difference in r.max() between two tessellations of the same solid
(delta_rmax = 0.000583 mm here) shifts every one of the 64 radial bin edges
(ri = r/rmax*(nbins-1)), so the same material lands in different bins and the joint
(r,z) occupancy IoU collapses. The symmetry AXIS is STABLE (0.0 deg between the two
clouds) — this is a binning-quantization bug, NOT an axis-tilt or angular-degeneracy
bug (correcting the original memory note's "in-plane angular degeneracy" guess).

FIX DIRECTION (verified here): a TOLERANT joint (r,z) comparison — dilate each
occupancy grid by ±1 bin before IoU — recovers iou 0.7826 -> 0.9310. This is the
tolerant-2-D fix in the plan (a numpy-only ±1-bin dilation in the real
implementation; scipy is used below only to PROVE the direction). It is a GUARDED
change to harness/geometry.py and needs explicit approval.

Run (from repo root, with the venv python):
    .venv/Scripts/python.exe scripts/iou_roundpart_diag.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from build123d import (BuildPart, BuildSketch, Circle, Cylinder, Ellipse, Align, Mode,
                       extrude, export_stl)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harness import geometry as G  # noqa: E402

# Standard ISO 608 bearing envelope (mm) — same as tasks/bearing_608/make_ground_truth.py,
# rebuilt here from the public standard dimensions (GT-free).
OD_R = 11.0   # outer radius (Ø22)
BORE_R = 4.0  # bore radius (Ø8)
WIDTH = 7.0   # axial width


def build_cyl_cyl():
    """Construction A: Cylinder - Cylinder."""
    with BuildPart() as p:
        Cylinder(radius=OD_R, height=WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Cylinder(radius=BORE_R, height=WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    return p.part


def build_circle_extrude():
    """Construction B: Circle - Circle extrude (lowers to the SAME mesh as A)."""
    with BuildPart() as p:
        with BuildSketch():
            Circle(radius=OD_R)
            Circle(radius=BORE_R, mode=Mode.SUBTRACT)
        extrude(amount=WIDTH)
    return p.part


def build_ellipse_extrude():
    """Construction C: Ellipse(R,R) - Circle extrude. A circle expressed as an ellipse
    with EQUAL radii — still perfectly round, but build123d tessellates it DIFFERENTLY
    (different vertex count), which is what exercises the 'two meshes of one solid' bug."""
    with BuildPart() as p:
        with BuildSketch():
            Ellipse(x_radius=OD_R, y_radius=OD_R)
            Circle(radius=BORE_R, mode=Mode.SUBTRACT)
        extrude(amount=WIDTH)
    return p.part


def to_mesh(part, tol: float) -> trimesh.Trimesh:
    """Export to STL at a tessellation tolerance and reload — the path the grader samples
    (it scores the STL, not the B-rep). Matches runner.py: export_stl(tolerance=0.05)."""
    ws = tempfile.mkdtemp(prefix="diag_")
    stl = os.path.join(ws, "p.stl")
    export_stl(part, stl, tolerance=tol)
    return trimesh.load(stl, force="mesh")


def project(pts: np.ndarray):
    """Replicate _cylindrical_iou.project() (mirrors harness/geometry.py:247-255) so we
    can inspect the axis + radial coordinate the real grader uses."""
    p = pts - pts.mean(0)
    w, v = np.linalg.eigh(np.cov(p.T))
    med = np.median(w)
    axis = int(np.argmax(np.abs(w - med)))
    n = v[:, axis]
    z = p @ n
    r = np.linalg.norm(p - np.outer(z, n), axis=1)
    return n, r, z


def is_byte_identical(a: trimesh.Trimesh, b: trimesh.Trimesh) -> bool:
    """Strict-ish mesh equality: same vertex COUNT and the sorted vertex coords match.
    (np.sort(axis=0) is per-column, so this is a necessary-not-sufficient check — good
    enough to distinguish 'identical tessellation' from 'genuinely different mesh'.)"""
    if a.vertices.shape != b.vertices.shape:
        return False
    return np.allclose(np.sort(a.vertices, axis=0), np.sort(b.vertices, axis=0))


def angle_deg(n0, n1) -> float:
    c = abs(float(np.dot(n0 / np.linalg.norm(n0), n1 / np.linalg.norm(n1))))
    return float(np.degrees(np.arccos(np.clip(c, 0.0, 1.0))))


def banner(s):
    print("\n" + "=" * 72 + f"\n  {s}\n" + "=" * 72)


def report_pair(label, a_part, b_part, tol=0.05):
    """Build two constructions, mesh both, and report whether the bug reproduces."""
    a, b = to_mesh(a_part, tol), to_mesh(b_part, tol)
    pa, pb = G._voxel_centers(a, res=48), G._voxel_centers(b, res=48)
    identical = is_byte_identical(a, b)
    na, ra, _ = project(pa)
    nb, rb, _ = project(pb)
    iou_ab = G.iou(a, b)            # THE REAL GRADER — load-bearing
    print(f"\n  [{label}]")
    print(f"    A verts={len(a.vertices):4d} vol={a.volume:8.3f}   "
          f"B verts={len(b.vertices):4d} vol={b.volume:8.3f}")
    print(f"    meshes byte-identical: {identical}   "
          f"both rot-symmetric: {G._is_rotationally_symmetric(pa) and G._is_rotationally_symmetric(pb)}")
    print(f"    axis angle: {angle_deg(na, nb):.4f} deg   "
          f"delta_rmax: {abs(ra.max() - rb.max()):.6f} mm")
    print(f"    iou(A,B) = {iou_ab:.4f}   self: iou(A,A)={G.iou(a,a):.4f} iou(B,B)={G.iou(b,b):.4f}")
    flag = "OK" if iou_ab >= 0.95 else "*** BUG: equal round solids score < 0.95 ***"
    print(f"    -> {flag}")
    return iou_ab


def main():
    print(__doc__.split("Run (")[0].split("FINDING")[0].strip())

    banner("Two constructions that lower to the SAME mesh (the original FALSE-negative case)")
    report_pair("Cyl-Cyl vs Circle-extrude", build_cyl_cyl(), build_circle_extrude())
    print("\n  ^ byte-identical meshes -> iou 1.0. This is why the first diagnostic")
    print("    wrongly concluded 'no bug'. It never made two DIFFERENT meshes.")

    banner("Same round solid built a DIFFERENT way -> the bug reproduces")
    iou_repro = report_pair("Circle-extrude vs Ellipse(R,R)-extrude",
                            build_circle_extrude(), build_ellipse_extrude())

    banner("MECHANISM + FIX DIRECTION (radial-bin quantization at geometry.py:259)")
    a = to_mesh(build_circle_extrude(), 0.05)
    b = to_mesh(build_ellipse_extrude(), 0.05)
    pa, pb = G._voxel_centers(a, res=48), G._voxel_centers(b, res=48)
    _, ra, za = project(pa)
    _, rb, zb = project(pb)
    rmax = max(ra.max(), rb.max())            # the shared frame — geometry.py:259
    zlo = min(za.min(), zb.min())
    zspan = (max(za.max(), zb.max()) - zlo) or 1.0

    def grid(r, z, nb=64):
        ri = np.clip((r / rmax * (nb - 1)).astype(int), 0, nb - 1)
        zi = np.clip(((z - zlo) / zspan * (nb - 1)).astype(int), 0, nb - 1)
        g = np.zeros((nb, nb), dtype=bool)
        g[ri, zi] = True
        return g

    def iou2(x, y):
        return float((x & y).sum() / (x | y).sum()) if (x | y).any() else 0.0

    ga, gb = grid(ra, za), grid(rb, zb)
    cur = iou2(ga, gb)
    # Prove the tolerant-grid direction. The REAL fix is a numpy-only +/-1 shift-OR;
    # scipy here is ONLY to demonstrate the direction in the diagnostic.
    try:
        from scipy.ndimage import binary_dilation
        tol_iou = iou2(binary_dilation(ga), binary_dilation(gb))
        tol_str = f"{tol_iou:.4f}"
    except Exception:
        tol_str = "(scipy unavailable — see plan; real fix is numpy +/-1 shift-OR)"
    print(f"  delta_rmax between the two tessellations: {abs(ra.max() - rb.max()):.6f} mm")
    print(f"  current joint-grid IoU (_cylindrical_iou): {cur:.4f}")
    print(f"  tolerant (+/-1 bin dilation) IoU:          {tol_str}   <- the fix direction")

    banner("VERDICT")
    if iou_repro < 0.95:
        print("  *** ROUND-PART IoU BUG CONFIRMED. ***")
        print("  Two geometrically-equal, genuinely-round annuli score iou < 0.95 through")
        print("  the real grader, deterministically. Root cause = radial-frame quantization")
        print("  (shared rmax at geometry.py:259 sampled from the clouds; sub-micron rmax")
        print("  delta shifts all radial bins). Axis is STABLE — not an angular/axis bug.")
        print("  Fix: tolerant joint (r,z) comparison (numpy +/-1 bin dilation), GUARDED,")
        print("  needs approval. See issue #7 / known-limitations.md §2.")
    else:
        print("  Did not reproduce here — widen the construction set / tessellation before")
        print("  concluding anything (the FIRST diagnostic's mistake was too narrow a set).")
    print()


if __name__ == "__main__":
    main()
