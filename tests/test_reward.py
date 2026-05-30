"""
test_reward.py — validate the grader and the sandbox runner.

Run from the repo root:   pytest -q
These tests use the sample bracket ground truth, so run
`python tasks/sample_bracket/make_ground_truth.py` first (setup.sh does this).
"""
import json
import sys
from pathlib import Path

import pytest
import trimesh

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harness import run_candidate, score, RewardConfig   # noqa: E402

GT_DIR = REPO / "tasks" / "sample_bracket" / "ground_truth"


def _gt():
    stl = GT_DIR / "result.stl"
    if not stl.exists():
        pytest.skip("ground truth not built; run tasks/sample_bracket/make_ground_truth.py")
    mesh = trimesh.load(str(stl), force="mesh")
    sig = json.loads((GT_DIR / "topology.json").read_text())
    return mesh, sig


def test_body_gate_rejects_empty():
    gt_mesh, gt_sig = _gt()
    r = score(None, gt_mesh, gt_sig=gt_sig)
    assert r.body == 0.0
    assert r.composite == 0.0


def test_identical_scores_high():
    gt_mesh, gt_sig = _gt()
    r = score(gt_mesh, gt_mesh, candidate_sig=gt_sig, gt_sig=gt_sig)
    assert r.body == 1.0
    assert r.volume == 1.0           # same mesh -> exact volume
    assert r.bbox == 1.0
    assert r.topology == 1.0         # identical signature (incl. euler)
    # Deterministic voxel IoU: a mesh against ITSELF must overlap perfectly.
    # This is the independent correctness gate for the P0.1 sampling-floor fix —
    # the old Monte-Carlo path capped here at ~0.975, which this assertion
    # would now reject.
    assert r.iou >= 0.999            # was > 0.9; deterministic voxelisation -> ~1.0
    assert r.composite > 0.95        # raised from 0.9 now that the IoU floor is gone


def test_iou_identical_is_exactly_one():
    """The core P0.1 property in isolation: deterministic IoU of any solid mesh
    against itself is 1.0 (no RNG, no sampling floor)."""
    gt_mesh, _ = _gt()
    from harness import geometry as G
    assert G.iou(gt_mesh, gt_mesh) >= 0.999


def test_siou_self_is_one():
    """Layer-7 in isolation: SIoU of a mesh against itself is ~1.0 (both directed
    fractions are 1.0 at any reasonable threshold)."""
    gt_mesh, _ = _gt()
    from harness import geometry as G
    assert G.surface_iou(gt_mesh, gt_mesh) >= 0.99


def test_siou_discriminates_wrong_shape():
    """SIoU must clearly penalise a wrong-shape candidate (a flat box where the
    GT is a curved cylinder) — i.e. score well below its self-value of ~1.0.

    (Note: SIoU is NOT necessarily lower than the *volumetric* IoU for this case
    — the two capture different errors. A box vs a same-footprint cylinder differs
    MORE in volume (the box's corners protrude) than in surface, so IoU can be the
    lower of the two here. They are complementary, which is the point of adding
    SIoU; the property we assert is that SIoU discriminates the wrong shape.)"""
    import trimesh
    from harness import geometry as G
    gt_cyl = trimesh.creation.cylinder(radius=10.0, height=5.0, sections=64)
    cand_box = trimesh.creation.box(extents=[20.0, 20.0, 5.0])
    siou_val = G.surface_iou(gt_cyl, cand_box)
    assert siou_val < 0.85, f"siou {siou_val:.3f} should clearly penalise wrong shape"
    # And it must be well below a self-comparison (which is ~1.0).
    assert siou_val < G.surface_iou(gt_cyl, gt_cyl) - 0.1


def test_reward_result_has_siou():
    """The composite wiring exposes the new siou field + includes it in summary."""
    gt_mesh, gt_sig = _gt()
    r = score(gt_mesh, gt_mesh, candidate_sig=gt_sig, gt_sig=gt_sig)
    assert hasattr(r, "siou") and r.siou >= 0.99
    assert "siou" in r.summary()


def test_wrong_size_scores_lower():
    gt_mesh, gt_sig = _gt()
    big = gt_mesh.copy()
    big.apply_scale(1.5)             # same shape, 1.5x bigger -> volume/bbox wrong
    r_id = score(gt_mesh, gt_mesh, candidate_sig=gt_sig, gt_sig=gt_sig)
    r_big = score(big, gt_mesh, gt_sig=gt_sig)
    assert r_big.volume < r_id.volume
    assert r_big.composite < r_id.composite


def test_runner_builds_and_grades_monotonic():
    """Full integration: sandbox-run two candidates of increasing fidelity and
    confirm the better one scores higher."""
    gt_mesh, gt_sig = _gt()
    right_box = ("from build123d import *\n"
                 "with BuildPart() as p:\n    Box(80, 50, 8)\n"
                 "result = p")
    full = (
        "from build123d import *\n"
        "with BuildPart() as p:\n"
        "    Box(80, 50, 8)\n"
        "    with Locations((-30,-18,0),(30,-18,0),(-30,18,0),(30,18,0)):\n"
        "        Hole(radius=2.5)\n"
        "    with BuildSketch():\n        SlotOverall(30, 8)\n"
        "    extrude(amount=-8, mode=Mode.SUBTRACT)\n"
        "result = p")

    tmp = REPO / "runs" / "_pytest"
    r1 = run_candidate(right_box, tmp / "box", timeout=120)
    r3 = run_candidate(full, tmp / "full", timeout=120)
    assert r1.ok and r3.ok, (r1.error, r3.error)

    s1 = score(r1.mesh, gt_mesh, candidate_sig=r1.topology, gt_sig=gt_sig)
    s3 = score(r3.mesh, gt_mesh, candidate_sig=r3.topology, gt_sig=gt_sig)
    assert s3.composite > s1.composite
    assert s3.topology == 1.0        # full part matches GT topology exactly
    assert s3.composite > 0.9
