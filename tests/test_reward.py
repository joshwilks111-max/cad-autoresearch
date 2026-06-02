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


def test_body_gate_fail_returns_well_formed_result():
    """Regression for the 2026-06-03 grid crash: the body-gate early-return
    (reward.py `if not body_ok`) built RewardResult with a bare positional `raw`,
    which (after siou became field #8) landed in the `siou` slot. That made siou a
    dict, so summary()'s f"{siou:.3f}" raised TypeError and KILLED the worker — the
    orchestrator then mislabelled the dead worker as "timeout after 120s". It also
    silently dropped the `raw` diagnostics that feedback.py reads.

    The existing test above only checks body/composite (the fields the bug does NOT
    corrupt), so it never caught this. This asserts the corrupted fields:
      - siou stays a float (not a dict),
      - summary() renders without raising,
      - raw carries the candidate_watertight flag feedback.py depends on.
    Fails pre-fix (TypeError in summary / dict siou); passes post-fix."""
    gt_mesh, gt_sig = _gt()
    r = score(None, gt_mesh, gt_sig=gt_sig)          # None candidate -> body gate fails
    assert isinstance(r.siou, float), f"siou must be a float, got {type(r.siou).__name__}"
    assert r.siou == 0.0
    assert isinstance(r.raw, dict) and r.raw.get("candidate_watertight") is False
    # The actual crash site: this must not raise.
    s = r.summary()
    assert "siou=0.000" in s


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


def test_topology_match_neutral_on_schema_mismatch():
    """A B-rep signature vs the cheap mesh proxy share only `euler`, and the two
    eulers are different quantities (B-rep V-E+F vs triangulation genus). Comparing
    them used to score a geometrically-correct candidate 0.0; the schema guard must
    instead return NEUTRAL 0.5 — while leaving same-schema comparisons exact."""
    from harness import geometry as G
    brep = {"faces": 15, "edges": 36, "vertices": 24, "shells": 1, "solids": 1, "euler": 3}
    mesh = {"components": 1, "euler": -8, "watertight": True}
    # cross-schema -> neutral, not a spurious 0.0
    assert G.topology_match(brep, mesh) == 0.5
    assert G.topology_match(mesh, brep) == 0.5
    # same-schema behaviour unchanged
    assert G.topology_match(brep, brep) == 1.0
    assert G.topology_match(mesh, mesh) == 1.0
    brep_wrong = {"faces": 42, "edges": 120, "vertices": 80, "shells": 1, "solids": 1, "euler": 2}
    assert G.topology_match(brep, brep_wrong) < 1.0   # real penalty preserved


def test_adaptive_weighting_keys_on_gt_faces():
    """Feature-rich GT shifts weight from the blind surface layers (chamfer, siou)
    into the sensitive ones (iou, topology); a simple GT is unchanged. The shift is
    keyed on the GT face count, so it is ungameable by the candidate."""
    from harness.reward import _adaptive_weights, RewardConfig
    cfg = RewardConfig()
    base = _adaptive_weights(cfg, None)             # no signature -> base weights
    simple = _adaptive_weights(cfg, 10)             # below afw_face_lo -> base
    rich = _adaptive_weights(cfg, 160)              # complex real part -> shifted
    assert base == simple
    assert simple["iou"] == cfg.w_iou               # untouched for simple parts
    assert rich["iou"] > base["iou"]                # sensitive layer up
    assert rich["chamfer"] < base["chamfer"]        # blind layer down
    assert rich["siou"] < base["siou"]              # blind layer down
    # total weight is conserved (we move weight between layers, not add it)
    assert abs(sum(rich.values()) - sum(base.values())) < 1e-9


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
