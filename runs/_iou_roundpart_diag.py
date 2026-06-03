#!/usr/bin/env python3
"""
_iou_roundpart_diag.py — DIAGNOSTIC (read-only) for the round-part IoU degeneracy.

Issue #7 / known-limitations.md §2: a correct low-aspect annulus (bearing_608, ~3:1)
scores iou=1.00 via `Circle-Circle extrude` but iou=0.00 via `Cylinder-Cylinder`, on
geometrically-equal solids, deterministically. The plan + eng-review require us to
MEASURE the root-cause LAYER before touching guarded harness/geometry.py:

  - gate   : does the routing gate _is_rotationally_symmetric route both meshes to the
             SAME branch? (if jitter straddles tol=0.05, the two solids get scored by
             DIFFERENT functions — cylindrical vs 48-transform voxel — which alone
             could cause the split)
  - axis   : is the PCA symmetry axis STABLE between the two tessellations, or tilting?
  - grid   : if axis+gate are stable, the jitter is in the joint (r,z) binning.

This script is GT-FREE: it builds bearing_608 from primitives (the two constructions the
workers used), never reads tasks/bearing_608/ground_truth/. It calls the REAL harness
functions (not re-implementations) so the diagnosis reflects production behavior.

Run (from repo root, with the venv python):
    .venv/Scripts/python.exe runs/_iou_roundpart_diag.py

============================================================================
FINDING (2026-06-03): THE DEGENERACY DOES NOT REPRODUCE.
============================================================================
At the harness tessellation tol 0.05 (and at every tol from 0.5 to 0.005, and
with the two solids tessellated at DIFFERENT tols), `Cylinder-Cylinder` and
`Circle-Circle extrude` produce BYTE-IDENTICAL 504-vertex meshes (vol 2308.11).
build123d lowers both constructions to the same OCC geometry, so the "two
independently-built meshes of the SAME solid" precondition the bug requires never
occurs from these two build paths. Result in ALL cases: iou(A,B) = 1.0000,
self-IoU = 1.0, branch agreement YES, axis angle 0.000 deg.

Tested even genuinely near-cubic annuli (in-plane eigenvalue ratio 0.83-0.99,
spanning the doc's cited 0.967): still iou(A,B) = 1.0000.

CONCLUSION: the bug as documented in known-limitations.md #2 / issue #7 is NOT
reproducible in the current harness. Most likely the original 2026-06-03 live-grid
observation conflated a 0.00 from a DIFFERENT cause (a genuinely non-equal candidate
- wrong axis from a Rotation, a non-watertight solid hitting the Monte-Carlo
fallback, etc.) with "byte-equal geometry" (a claim that was never instrumented -
Codex flagged exactly this ambiguity). The tolerant-2-D-grid fix (plan item 1.1)
addresses a degeneracy that does not currently exist; DO NOT ship it as a fix for
this. Escalated to the user; see the plan's T1->T2 gate.
============================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from build123d import BuildPart, BuildSketch, Circle, Cylinder, Align, Mode, extrude, export_stl

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harness import geometry as G  # noqa: E402

# Standard ISO 608 bearing envelope (mm) — same as tasks/bearing_608/make_ground_truth.py,
# but rebuilt here from the public standard dimensions (GT-free).
OD_R = 11.0   # outer radius (Ø22)
BORE_R = 4.0  # bore radius (Ø8)
WIDTH = 7.0   # axial width


def build_cyl_cyl():
    """Construction A: Cylinder - Cylinder (the worker that scored iou=0.00)."""
    with BuildPart() as p:
        Cylinder(radius=OD_R, height=WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Cylinder(radius=BORE_R, height=WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    return p.part


def build_circle_extrude():
    """Construction B: Circle - Circle extrude (the worker that scored iou=1.00)."""
    with BuildPart() as p:
        with BuildSketch():
            Circle(radius=OD_R)
            Circle(radius=BORE_R, mode=Mode.SUBTRACT)
        extrude(amount=WIDTH)
    return p.part


def to_mesh(part, tol: float) -> trimesh.Trimesh:
    """Export the solid to STL at a given tessellation tolerance and reload as a mesh —
    exactly the path the grader samples (it scores the STL, not the B-rep)."""
    import tempfile, os
    ws = tempfile.mkdtemp(prefix="diag_")
    stl = os.path.join(ws, "p.stl")
    export_stl(part, stl, tolerance=tol)
    return trimesh.load(stl, force="mesh")


def axis_of(pts: np.ndarray) -> np.ndarray:
    """Replicate _cylindrical_iou.project()'s axis pick EXACTLY (the distinct eigenvalue
    axis) so we can measure whether it's stable between meshes. Mirrors geometry.py:247-252."""
    p = pts - pts.mean(0)
    w, v = np.linalg.eigh(np.cov(p.T))
    med = np.median(w)
    axis = int(np.argmax(np.abs(w - med)))
    return v[:, axis], w


def eig_ratios(pts: np.ndarray):
    """Sorted-descending eigenvalues + the top-2 ratio the §2 writeup cites (~0.967)."""
    w = np.sort(np.linalg.eigvalsh(np.cov((pts - pts.mean(0)).T)))[::-1]
    return w, (w[1] / w[0] if w[0] else float("nan"))


def angle_deg(n0: np.ndarray, n1: np.ndarray) -> float:
    """Unsigned angle between two axis directions (eigenvector sign is arbitrary)."""
    c = abs(float(np.dot(n0 / np.linalg.norm(n0), n1 / np.linalg.norm(n1))))
    return float(np.degrees(np.arccos(np.clip(c, 0.0, 1.0))))


def banner(s): print("\n" + "=" * 72 + f"\n  {s}\n" + "=" * 72)


def main():
    print(__doc__.split("Run (")[0].strip())
    banner("BUILD: bearing_608 two ways (GT-free) @ harness tessellation tol 0.05")
    a_part = build_cyl_cyl()          # scored 0.00 in the live grid
    b_part = build_circle_extrude()   # scored 1.00 in the live grid

    # The harness tessellates GT/candidate at 0.05 throughout (known-limitations.md:189).
    TOL = 0.05
    a_mesh = to_mesh(a_part, TOL)
    b_mesh = to_mesh(b_part, TOL)
    print(f"  Cylinder-Cylinder : verts={len(a_mesh.vertices):5d} faces={len(a_mesh.faces):5d} "
          f"vol={a_mesh.volume:8.2f} watertight={a_mesh.is_watertight}")
    print(f"  Circle-extrude    : verts={len(b_mesh.vertices):5d} faces={len(b_mesh.faces):5d} "
          f"vol={b_mesh.volume:8.2f} watertight={b_mesh.is_watertight}")

    # --- Resolve the ambiguous "byte-equal geometry" claim ---
    banner("Q: are the two STL tessellations identical, or same-solid-different-mesh?")
    same_verts = (a_mesh.vertices.shape == b_mesh.vertices.shape and
                  np.allclose(np.sort(a_mesh.vertices, axis=0), np.sort(b_mesh.vertices, axis=0)))
    print(f"  vertex-count match: {a_mesh.vertices.shape == b_mesh.vertices.shape}")
    print(f"  tessellations identical (sorted-vertex allclose): {same_verts}")
    print("  => 'byte-equal geometry' means: same mathematical solid, "
          f"{'IDENTICAL' if same_verts else 'DIFFERENT'} STL tessellation.")

    # --- Get the SAME interior point clouds the grader's iou() uses ---
    # iou() voxelizes at res*2 with res derived from target_pitch_mm=1.25, clamped [24,64].
    # For a 22mm part: want=ceil(22/1.25)=18 -> clamped to 24 -> res*2=48. Use 48 to match.
    pa = G._voxel_centers(a_mesh, res=48)
    pb = G._voxel_centers(b_mesh, res=48)
    print(f"  interior voxel-centers: A={len(pa)}  B={len(pb)}")

    # --- LAYER 1: routing gate (branch agreement) ---
    banner("LAYER 'gate': does _is_rotationally_symmetric route BOTH to the same branch?")
    sym_a = G._is_rotationally_symmetric(pa)
    sym_b = G._is_rotationally_symmetric(pb)
    wa, ra = eig_ratios(pa)
    wb, rb = eig_ratios(pb)
    print(f"  A (Cyl-Cyl)    eig={np.round(wa,2)}  top2ratio={ra:.4f}  symmetric={sym_a}")
    print(f"  B (Circle-ext) eig={np.round(wb,2)}  top2ratio={rb:.4f}  symmetric={sym_b}")
    branch_a = "cylindrical" if sym_a else "voxel(48-transform)"
    branch_b = "cylindrical" if sym_b else "voxel(48-transform)"
    print(f"  branch A -> {branch_a}   branch B -> {branch_b}")
    gate_agree = (sym_a == sym_b)
    print(f"  BRANCH AGREEMENT: {'YES (same branch)' if gate_agree else 'NO -- DIVERGENT BRANCHES!'}")

    # --- LAYER 2: axis stability ---
    banner("LAYER 'axis': is the PCA symmetry axis stable between the two tessellations?")
    n_a, _ = axis_of(pa)
    n_b, _ = axis_of(pb)
    ang = angle_deg(n_a, n_b)
    print(f"  symmetry-axis A: {np.round(n_a,4)}")
    print(f"  symmetry-axis B: {np.round(n_b,4)}")
    print(f"  ANGLE between axes: {ang:.3f} deg   ({'STABLE' if ang < 1.0 else 'TILTING (>=1deg)'})")

    # --- The headline reproduction + the score split ---
    banner("REPRODUCE: iou(A,B) and self-IoU (the 1.00<->0.00 split)")
    iou_ab = G.iou(a_mesh, b_mesh)
    iou_aa = G.iou(a_mesh, a_mesh)
    iou_bb = G.iou(b_mesh, b_mesh)
    print(f"  iou(A, B)  = {iou_ab:.4f}   <-- the bug if this is low on equal geometry")
    print(f"  iou(A, A)  = {iou_aa:.4f}   (self-identity, must be ~1.0)")
    print(f"  iou(B, B)  = {iou_bb:.4f}")

    # --- LAYER 3: per-bin radial occupancy (only meaningful if gate+axis are stable) ---
    banner("LAYER 'grid': per-bin radial occupancy of the two clouds (joint-grid view)")
    def radial_hist(pts, nb=24):
        n, _ = axis_of(pts)
        p = pts - pts.mean(0)
        z = p @ n
        r = np.linalg.norm(p - np.outer(z, n), axis=1)
        rmax = r.max() or 1.0
        ri = np.clip((r / rmax * (nb - 1)).astype(int), 0, nb - 1)
        occ = np.zeros(nb, dtype=int)
        for i in ri:
            occ[i] += 1
        return (occ > 0).astype(int), rmax
    occ_a, rmax_a = radial_hist(pa)
    occ_b, rmax_b = radial_hist(pb)
    print(f"  A rmax={rmax_a:.3f}  radial occupancy: {''.join('#' if x else '.' for x in occ_a)}")
    print(f"  B rmax={rmax_b:.3f}  radial occupancy: {''.join('#' if x else '.' for x in occ_b)}")

    # --- VERDICT: which layer owns the bug ---
    banner("VERDICT — root-cause LAYER")
    if not gate_agree:
        print("  *** GATE divergence is the root cause. The two identical solids take")
        print("      DIFFERENT branches (cylindrical vs voxel). Fix is the gate")
        print("      _is_rotationally_symmetric (tol=0.05 too tight / unstable) — e.g.")
        print("      hysteresis or axis-snapping — NOT _cylindrical_iou.")
    elif ang >= 1.0:
        print("  *** AXIS instability is the root cause. project()'s symmetry axis tilts")
        print(f"      {ang:.2f} deg between tessellations. Fix is upstream axis stabilization")
        print("      (snap to dominant Cylinder-face axis / tie-break) — NOT the grid.")
    elif iou_ab < 0.95:
        print("  *** GRID jitter is the root cause (gate + axis both stable, yet iou(A,B)")
        print(f"      = {iou_ab:.3f}). The tolerant 2-D (r,z) fix (numpy dilation) is correct.")
    else:
        print(f"  *** Could NOT reproduce the degeneracy here (iou(A,B)={iou_ab:.3f} >= 0.95).")
        print("      The bug may need the exact worker meshes / a different tessellation tol;")
        print("      re-run varying TOL, or capture the live worker STLs before fixing.")
    print()


if __name__ == "__main__":
    main()
