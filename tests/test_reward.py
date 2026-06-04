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


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_wrong_size_scores_lower():
    gt_mesh, gt_sig = _gt()
    big = gt_mesh.copy()
    big.apply_scale(1.5)             # same shape, 1.5x bigger -> volume/bbox wrong
    r_id = score(gt_mesh, gt_mesh, candidate_sig=gt_sig, gt_sig=gt_sig)
    r_big = score(big, gt_mesh, gt_sig=gt_sig)
    assert r_big.volume < r_id.volume
    assert r_big.composite < r_id.composite


@pytest.mark.slow
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


def test_runner_relative_workspace_does_not_double_path():
    """Regression for the 2026-06-03 grid zeroing: run_candidate ran the subprocess
    with cwd=workspace but passed a still-RELATIVE script path, so the OS re-resolved
    it against the new cwd -> a doubled path (runs/x/.../runs/x/.../candidate.py) ->
    "can't open file" -> candidate exited 2 -> graded body=0. With the orchestrator and
    --run-dir both passing relative run dirs, this zeroed EVERY worker's build.

    The existing runner test above only ever used an ABSOLUTE workspace (REPO/...), so
    it never caught this. This passes a RELATIVE workspace — the exact production
    condition. Fails pre-fix (r.ok False, 'exited 2'); passes post-fix (ws.resolve()).

    cwd is changed to REPO so the relative path is well-defined, then restored."""
    import os
    code = ("from build123d import *\n"
            "with BuildPart() as p:\n    Box(10, 10, 10)\n"
            "result = p")
    rel_ws = os.path.join("runs", "_pytest_relws", "ws")
    prev = os.getcwd()
    try:
        os.chdir(str(REPO))
        r = run_candidate(code, rel_ws, timeout=120)
    finally:
        os.chdir(prev)
    assert r.ok, f"relative workspace must build, not double the path; error={r.error!r}"
    assert r.error is None


# --- round-part cylindrical-IoU regression (the 2026-06-04 washer-inversion fix) ---

def _round_mesh(kind: str, od: float, bore: float, w: float):
    """Build an annulus/stepped-shaft IN-TEST and return its trimesh (GT-free — these
    are self-built primitives, never read from any ground_truth/). `kind`:
    'circle' / 'ellipse' produce the SAME annulus via two tessellations (Circle vs
    equal-radii Ellipse); 'stepped'/'plain' build axially-structured controls."""
    import tempfile, os
    from build123d import (BuildPart, BuildSketch, Circle, Ellipse, extrude, Plane,
                           Mode, Cylinder, Align, Axis, export_stl)
    if kind in ("circle", "ellipse"):
        e = kind == "ellipse"
        with BuildPart() as bp:
            with BuildSketch(Plane.XY):
                (Ellipse(od / 2, od / 2) if e else Circle(od / 2))
                (Ellipse(bore / 2, bore / 2, mode=Mode.SUBTRACT) if e
                 else Circle(bore / 2, mode=Mode.SUBTRACT))
            extrude(amount=w)
        part = bp.part
    elif kind == "stepped":          # Ø(od)×(w) then Ø(bore)×(w) stacked along Z
        with BuildPart() as bp:
            Cylinder(od / 2, w, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with BuildPart(bp.part.faces().sort_by(Axis.Z)[-1]):
                Cylinder(bore / 2, w, align=(Align.CENTER, Align.CENTER, Align.MIN))
        part = bp.part
    else:                            # 'plain' Ø(od)×(w)
        with BuildPart() as bp:
            Cylinder(od / 2, w)
        part = bp.part
    fd, p = tempfile.mkstemp(suffix=".stl"); os.close(fd)
    export_stl(part, p, tolerance=0.05)
    m = trimesh.load(p, force="mesh"); os.unlink(p)
    return m


@pytest.mark.slow
def test_round_part_iou_no_washer_inversion():
    """Regression for the 2026-06-04 cylindrical-IoU bug: a CORRECT round part scored
    LOWER than a WRONG-bore one (the grader preferred wrong geometry), because the joint
    (r, axial) grid was too axially sensitive for thin parts — a washer's ~3mm extent
    over 64 axial bins scattered the same radial ring across bins for two tessellations,
    and the axial-sign search landed a half-overlap. The fix: radial sharp (64 bins) +
    axial coarse (32 bins) + ±1 axial dilation, in harness/geometry._cylindrical_iou.

    There was NO round-part IoU test before this (the suite only used the prismatic
    sample_bracket), which is why the bug shipped and survived multiple sessions. All
    parts are built in-test, GT-free. Asserts, through the real G.iou entry point:
      - bearing_608 cross-tessellation (Circle vs Ellipse, byte-DIFFERENT meshes) ≥0.95;
      - a CORRECT washer scores clearly ABOVE a WRONG-bore one (the inversion);
      - round-part self-identity is exactly 1.0 (the fix didn't break self-overlap);
      - radial sharpness is preserved: a stepped shaft still beats a plain cylinder of
        the same envelope (radial-only would false-positive here — the lossy trap)."""
    from harness import geometry as G
    # bearing_608 (OD22/bore8/w7) built two ways — same solid, different tessellation
    bear_a = _round_mesh("circle", 22, 8, 7)
    bear_b = _round_mesh("ellipse", 22, 8, 7)
    assert G.iou(bear_a, bear_a) >= 0.999, "round self-identity must be 1.0"
    assert G.iou(bear_a, bear_b) >= 0.95, "byte-equal round solids must score high"

    # thin washer (OD63/t3): correct cross-tessellation vs wrong bore (Ø42 not Ø32)
    wash_a = _round_mesh("circle", 63, 32, 3)
    wash_b = _round_mesh("ellipse", 63, 32, 3)
    wash_wrong = _round_mesh("circle", 63, 42, 3)
    assert G.iou(wash_a, wash_a) >= 0.999
    right = G.iou(wash_a, wash_b)
    wrong = G.iou(wash_a, wash_wrong)
    assert right > wrong + 0.05, (
        f"correct washer ({right:.3f}) must beat wrong-bore ({wrong:.3f}) — the inversion")

    # radial sharpness preserved: stepped shaft must NOT look like a plain cylinder
    step = _round_mesh("stepped", 20, 12, 10)        # Ø20×10 + Ø12×10
    plain = _round_mesh("plain", 20, 0, 20)          # Ø20×20, same envelope
    assert G.iou(step, step) >= 0.999
    assert G.iou(step, step) > G.iou(step, plain) + 0.05, (
        "stepped vs plain must differ — radial-only would false-positive here")


def test_axial_dilation_does_not_wrap_across_ends():
    """Regression for the axial-dilation WRAP bug (caught in /review of the inversion fix):
    the ±1 axial dilation must use SLICE shifts, NOT np.roll. A part's axial extent fills
    bins 0..N-1 INCLUSIVE, so np.roll would wrap the top bin's material into the bottom bin
    (and vice versa) — material at one axial extreme spuriously appears at the other.

    Exercises the PRODUCTION helper `geometry._dilate_axial` directly (NOT a local copy —
    a copy would pass even if production regressed to np.roll). A True cell in the LAST
    axial column must dilate ONLY into its neighbour (col N-2), never wrap to col 0; same
    for col 0. Also checks self-identity: dilation must be radial-axis-preserving so a grid
    dilated == its own dilation (idempotent shape) — the dilation must not touch radial."""
    import numpy as np
    from harness.geometry import _dilate_axial
    nb = 32
    g = np.zeros((4, nb), dtype=bool)
    g[0, 0] = True            # material at the LOW axial extreme
    g[1, nb - 1] = True       # material at the HIGH axial extreme
    g[2, 5] = True            # a mid-axial cell (radial row 2)
    d = _dilate_axial(g)
    # low-end cell spreads to col 1 only — NOT wrapping to the high end
    assert d[0, 0] and d[0, 1] and not d[0, nb - 1], "low-end dilation must not wrap to the top"
    # high-end cell spreads to col N-2 only — NOT wrapping to col 0
    assert d[1, nb - 1] and d[1, nb - 2] and not d[1, 0], "high-end dilation must not wrap to the bottom"
    # mid cell spreads to both axial neighbours, stays in its radial row (no radial bleed)
    assert d[2, 4] and d[2, 5] and d[2, 6], "mid-axial cell must spread to both axial neighbours"
    assert not d[1, 5] and not d[3, 5], "dilation must NOT cross radial rows (radial stays sharp)"


@pytest.mark.slow
def test_round_part_iou_shallow_groove_is_a_known_limitation():
    """DOCUMENTS (does not fail on) the metric-inherent insensitivity the /review flagged:
    the volumetric cylindrical IoU is ~insensitive to a SHALLOW external groove because the
    groove removes a tiny volume band, so (r,z) occupancy barely changes — this holds at ANY
    axial resolution, NOT a regression of the 32-bin fix. Shallow grooves are the TOPOLOGY +
    CHAMFER layers' job, not IoU's. This test locks the EXPECTED behaviour so a future reader
    doesn't 'fix' the IoU layer by sharpening axial bins (which re-breaks the washer inversion
    for ~0.004 of groove signal). If a future change makes IoU groove-sensitive AND keeps the
    washer fixed, update this test — that would be a genuine improvement."""
    from harness import geometry as G
    plain_cyl = _round_mesh("plain", 40, 0, 30)             # Ø40 × 30
    # a grooved cylinder: same envelope, a shallow external groove removes ~a few % volume.
    # Built as plain minus a thin outer band at mid-height (core added back).
    import tempfile, os
    from build123d import BuildPart, Cylinder, Mode, export_stl
    with BuildPart() as bp:
        Cylinder(20, 30)
        with BuildPart(mode=Mode.SUBTRACT):
            Cylinder(21, 5)        # remove a 5mm-tall slab to OD+1
        with BuildPart(mode=Mode.ADD):
            Cylinder(14, 5)        # add the core back -> only the outer rim band is gone
    fd, p = tempfile.mkstemp(suffix=".stl"); os.close(fd)
    export_stl(bp.part, p, tolerance=0.05)
    grooved = trimesh.load(p, force="mesh"); os.unlink(p)
    iou_gp = G.iou(grooved, plain_cyl)
    # EXPECTED: high (~0.95+) — the IoU layer does not see a shallow groove. This is the
    # documented limitation, not a bug. (Asserting > 0.85 keeps the test from being a no-op
    # while encoding that groove-vs-plain is NOT well-discriminated by IoU alone.)
    assert iou_gp > 0.85, (
        f"shallow groove vs plain IoU={iou_gp:.3f}: expected HIGH (IoU is groove-insensitive "
        f"by design — topology/chamfer layers catch grooves). If this dropped, the metric changed.")
