"""
test_hole_metrics.py — lock hole-detection counts for the just-rewritten logic.

The hole detectors (hole_metrics + regiondiff._all_holes) were rewritten in the
toolbuild + hardened in the /review pass (all-axis sweep, dense placement with a 64
cap, cv<0.15 gate, >=2-plane confirmation). This is the riskiest code in that work and
had ZERO tests. These lock the behavior so a future tweak to cv_max / min_plane_hits /
step_mm / cap can't silently regress the count.

Meshes are built in-process (no ground_truth/ files needed). Run from repo root:
   pytest -q tests/test_hole_metrics.py
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
import trimesh

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from build123d import (BuildPart, Box, Cylinder, Locations, Mode, Align,  # noqa: E402
                       export_stl)
from hole_metrics import hole_metrics  # noqa: E402
import regiondiff as rd  # noqa: E402


def _mesh(part, tol=0.05):
    ws = tempfile.mkdtemp(prefix="test_hm_")
    stl = os.path.join(ws, "p.stl")
    export_stl(part, stl, tolerance=tol)
    return trimesh.load(stl, force="mesh")


def _box_with_through_z():
    with BuildPart() as p:
        Box(40, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Cylinder(radius=5, height=30, align=(Align.CENTER,) * 3, mode=Mode.SUBTRACT)
    return p.part


# ── single hole, through vs blind ──────────────────────────────────────────
def test_single_through_bore():
    r = hole_metrics(_mesh(_box_with_through_z()))
    assert r["n_holes"] == 1 and r["n_through"] == 1 and r["n_blind"] == 0


def test_blind_hole_classified_blind():
    with BuildPart() as p:
        Box(40, 40, 20, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((0, 0, 5)):  # bore opens at top, floors mid-body
            Cylinder(radius=5, height=10, align=(Align.CENTER,) * 3, mode=Mode.SUBTRACT)
    r = hole_metrics(_mesh(p.part))
    assert r["n_holes"] == 1 and r["n_blind"] == 1


# ── circularity gate: a SQUARE pocket is not a round hole ───────────────────
def test_square_pocket_not_counted_as_hole():
    with BuildPart() as p:
        Box(40, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Box(8, 8, 30, mode=Mode.SUBTRACT)
    assert hole_metrics(_mesh(p.part))["n_holes"] == 0


# ── large-part placement: a near-end bore in a 200mm bar is found ───────────
def test_bore_in_large_part_found():
    """Regression for the 13-plane-cap bug: a bore in a 200mm part must not be
    silently dropped by too-coarse section spacing."""
    with BuildPart() as p:
        Box(200, 20, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((90, 0, 10)):
            Cylinder(radius=4, height=40, align=(Align.CENTER,) * 3, mode=Mode.SUBTRACT)
    assert hole_metrics(_mesh(p.part))["n_holes"] == 1


# ── multi-axis: holes on two perpendicular axes both counted ────────────────
def test_two_distinct_close_holes_not_merged():
    """Two Z-bores 10mm apart must count as 2 (dedup must not over-merge)."""
    with BuildPart() as p:
        Box(60, 60, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((-5, 0, 0), (5, 0, 0)):
            Cylinder(radius=4, height=30, align=(Align.CENTER,) * 3, mode=Mode.SUBTRACT)
    assert hole_metrics(_mesh(p.part))["n_holes"] == 2


# ── THE CANARY: L-bracket 6-hole part scores 4/6 (documented limitation) ────
def test_lbracket_documented_4_of_6():
    """L-bracket spec = 6 holes (4 base along Z + 2 wall along Y). Mesh-section
    detection finds the 4 base holes; the 2 wall holes (through a thin wall PARALLEL
    to the section) don't close as inner loops -> 4/6. This asserts the CURRENT count
    on BOTH detectors. If detection improves (B-rep cylinder-face primitive) this trips
    -- update the literal to the new count. If it silently drops to 2/6 or 3/6, this
    trips too. Either way the change becomes a conscious decision, not a silent drift."""
    gt = REPO / "tasks" / "trial_lbracket" / "ground_truth" / "result.stl"
    if not gt.exists():
        pytest.skip("trial_lbracket GT not built (run its make_ground_truth.py)")
    mesh = trimesh.load(str(gt), force="mesh")
    hm_n = hole_metrics(mesh)["n_holes"]
    lo, hi = mesh.bounds[0], mesh.bounds[1]
    rd_n = len(rd._all_holes(mesh, lo, hi, tol=max(3 * 2.0, 4.0)))
    assert hm_n == 4, f"hole_metrics L-bracket count drifted: {hm_n} (was 4/6)"
    assert rd_n == 4, f"regiondiff L-bracket count drifted: {rd_n} (was 4/6)"
