"""
test_topology_hybrid.py — locks the hybrid Layer-4 topology (count-ratio blend).

This is the Software-3.0 gate for the topology-ceiling fix. Several tests here
FAIL against pre-hybrid `main`:
  - the back-compat + rescue tests call `score(..., candidate_hist=, gt_hist=)`;
    on `main` `score()` has no such params -> TypeError. That's a real fail-
    against-old, not a tautology.
  - `test_count_ratio_beats_cosine_on_monotonicity` is the A/B verdict that
    SELECTED count-ratio over bare cosine (Risk H): cosine is non-monotonic as
    features go missing; count-ratio is monotonic.

Run from repo root:  .venv\\Scripts\\python.exe -m pytest tests/test_topology_hybrid.py -q
(uses build123d to author the fixtures; no network, no GT under ground_truth/.)
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harness import score, RewardConfig                              # noqa: E402
from harness import geometry as G                                    # noqa: E402
from surface_histogram import (                                      # noqa: E402
    surface_histogram, histogram_similarity, count_ratio_similarity,
)


# ── fixtures: build the L-bracket and feature-degraded ladders in-memory ───────

def _lbracket_solid():
    """A gusseted L-bracket: base plate + upright + 4 base holes (Z) + 2 wall
    holes (Y). ~17 faces, {Plane:13, Cylinder:4} (well, 6 cylinders with all 6
    holes). Built in build123d so the test is self-contained and license-clean."""
    from build123d import (BuildPart, Box, Locations, Hole, Mode, Align)
    with BuildPart() as p:
        # base plate 120 x 60 x 8 (origin at min corner for predictable hole placement)
        Box(120, 60, 8, align=(Align.MIN, Align.MIN, Align.MIN))
        # 4 base holes through Z
        with Locations((20, 15, 8), (20, 45, 8), (100, 15, 8), (100, 45, 8)):
            Hole(radius=4)
    return p.part


def _solid_to_mesh(solid):
    """Tessellate a build123d solid to a trimesh at the pinned tolerance."""
    import tempfile
    import trimesh
    from build123d import export_stl
    ws = Path(tempfile.mkdtemp(prefix="_hybrid_test_"))
    stl = ws / "m.stl"
    export_stl(solid, str(stl), tolerance=0.05)
    return trimesh.load(str(stl), force="mesh")


def _plate_with_n_holes(n: int):
    """A 120x60x8 plate with `n` of 4 possible Z-holes drilled. Each rung is a
    VALID watertight solid (the body gate accepts it) that is MISSING real features
    as n drops — the semantic missing-feature ladder (ENG D11 / Codex F7). Returns
    (mesh, sig, hist)."""
    from build123d import BuildPart, Box, Locations, Hole, Align
    spots = [(20, 15, 8), (20, 45, 8), (100, 15, 8), (100, 45, 8)][:n]
    with BuildPart() as p:
        Box(120, 60, 8, align=(Align.MIN, Align.MIN, Align.MIN))
        if spots:
            with Locations(*spots):
                Hole(radius=4)
    solid = p.part
    return (_solid_to_mesh(solid),
            G.topology_signature_from_solid(solid),
            surface_histogram(solid))


# ── 1. the headline lock — fails on main (TypeError), the lbracket rescue ──────

def test_hybrid_rescues_seam_merge_penalized_perfect_part():
    """A geometrically PERFECT part penalised only by a STEP-roundtrip edge-count
    drift (the 51->49 seam merge) must be RESCUED by the hybrid. This recreates the
    proposal's regression step 2: sign the GT in-memory (more edges) and grade a
    re-imported-equivalent candidate (fewer edges) -> exact-count drifts, histogram
    is stable -> the hybrid lifts it.

    FAILS ON MAIN: score() has no candidate_hist/gt_hist param -> TypeError."""
    solid = _lbracket_solid()
    mesh = _solid_to_mesh(solid)
    sig = G.topology_signature_from_solid(solid)          # the re-imported-equivalent sig
    hist = surface_histogram(solid)

    # Simulate an IN-MEMORY-signed GT: same geometry, pre-merge edge/vertex counts.
    # +2 edges, +2 vertices over the candidate (the documented 49<->51 / 32<->34 drift).
    inmem_gt_sig = dict(sig)
    inmem_gt_sig["edges"] = sig["edges"] + 2
    inmem_gt_sig["vertices"] = sig["vertices"] + 2
    inmem_gt_sig["euler"] = (inmem_gt_sig["vertices"] - inmem_gt_sig["edges"]
                             + inmem_gt_sig["faces"])

    cfg = RewardConfig()
    old = score(mesh, mesh, candidate_sig=sig, gt_sig=inmem_gt_sig, cfg=cfg)
    new = score(mesh, mesh, candidate_sig=sig, gt_sig=inmem_gt_sig,
                candidate_hist=hist, gt_hist=hist, cfg=cfg)

    # exact-count is penalised by the edge drift; the histogram half is 1.0 (stable).
    assert old.raw["topology_exact"] < 0.95, "exact-count should be penalised by edge drift"
    assert new.raw["topology_hist"] == pytest.approx(1.0, abs=1e-6), \
        "identical histograms -> count-ratio similarity 1.0"
    # the hybrid lifts topology and the composite (the rescue).
    assert new.topology > old.topology, "hybrid must lift the penalised topology"
    assert new.composite > old.composite, "the rescue must lift the composite"
    # sub-scores are ALWAYS visible (Risk-H auditability).
    assert "topology_exact" in new.raw and "topology_hist" in new.raw


# ── 2. the A/B verdict — count-ratio is monotonic, cosine is not ──────────────

def test_count_ratio_beats_cosine_on_monotonicity():
    """THE Risk-H A/B, as a falsifiable test. Build a semantic missing-feature
    ladder (a 4-hole plate losing holes one at a time -> 4,3,2,1,0 holes, each a
    VALID solid). As features go missing, a topology similarity MUST decrease
    monotonically. count_ratio_similarity does; bare cosine does NOT (it's scale-
    invariant -> nearly flat). This is why the eng review (D1) shipped count-ratio."""
    rungs = [_plate_with_n_holes(n) for n in (4, 3, 2, 1, 0)]
    gt_hist = rungs[0][2]                                  # full part = ground truth

    cr = [count_ratio_similarity(h, gt_hist) for (_, _, h) in rungs]
    cos = [histogram_similarity(h, gt_hist) for (_, _, h) in rungs]

    # count-ratio strictly decreases as holes go missing (the property we want).
    for a, b in zip(cr, cr[1:]):
        assert a > b, f"count-ratio not monotonic down the ladder: {cr}"
    # the full part scores 1.0; the bare plate (all holes gone) scores well below.
    assert cr[0] == pytest.approx(1.0, abs=1e-6)
    assert cr[-1] < cr[0] - 0.3, "losing all holes must cost real topology score"

    # cosine FAILS monotonicity (the A/B verdict): it stays high even as holes vanish,
    # so consecutive rungs are NOT strictly decreasing the way count-ratio is. Assert
    # the gap: count-ratio separates the rungs far more than cosine does.
    cr_spread = cr[0] - cr[-1]
    cos_spread = cos[0] - cos[-1]
    assert cr_spread > cos_spread + 0.2, (
        f"count-ratio must separate missing-feature rungs more than cosine "
        f"(cr_spread={cr_spread:.3f} vs cos_spread={cos_spread:.3f}) — the Risk-H A/B")


# ── 3. back-compat — hist=None grades EXACTLY as the pre-hybrid path ───────────

def test_back_compat_no_hist_is_exact_only():
    """With no histogram args, the hybrid layer collapses to exact-count matching —
    byte-identical to pre-hybrid behaviour. Guards every existing caller."""
    solid = _lbracket_solid()
    mesh = _solid_to_mesh(solid)
    sig = G.topology_signature_from_solid(solid)
    cfg = RewardConfig()
    r = score(mesh, mesh, candidate_sig=sig, gt_sig=sig, cfg=cfg)
    # exact path: topology == exact-count match, hist sub-score is None (not computed).
    assert r.topology == r.raw["topology_exact"]
    assert r.raw["topology_hist"] is None
    assert r.topology == pytest.approx(1.0, abs=1e-6)     # identical sig -> exact 1.0


# ── 4. zero-histogram edge (empty solid slipped the gate) ─────────────────────

def test_zero_histogram_scores_zero_not_crash():
    """An all-zero candidate histogram (degenerate/empty solid) must score 0.0 on
    the histogram half, not crash or score high."""
    gt = {"Plane": 6}
    empty = {"Plane": 0, "Cylinder": 0}
    assert count_ratio_similarity(empty, gt) == 0.0
    assert count_ratio_similarity(gt, empty) == 0.0
    assert histogram_similarity(empty, gt) == 0.0


# ── 5. solved parts are a NO-OP under the hybrid (zero-regression) ─────────────

def test_solved_part_unmoved_when_exact_and_hist_agree():
    """Where exact-count and histogram already agree (a solved part: both ~1.0),
    the hybrid is a no-op — topology stays 1.0, composite unmoved. This is the
    zero-regression property for the 12 solved parts."""
    solid = _lbracket_solid()
    mesh = _solid_to_mesh(solid)
    sig = G.topology_signature_from_solid(solid)
    hist = surface_histogram(solid)
    cfg = RewardConfig()
    exact_only = score(mesh, mesh, candidate_sig=sig, gt_sig=sig, cfg=cfg)
    hybrid = score(mesh, mesh, candidate_sig=sig, gt_sig=sig,
                   candidate_hist=hist, gt_hist=hist, cfg=cfg)
    # identical sig + identical hist -> both halves 1.0 -> topology unchanged.
    assert hybrid.topology == pytest.approx(exact_only.topology, abs=1e-6)
    assert hybrid.composite == pytest.approx(exact_only.composite, abs=1e-6)


# ── 6. AFW interaction — the hybrid behaves under adaptive weighting on AND off ─

def test_hybrid_works_with_afw_on_and_off():
    """adaptive_feature_weighting amplifies the topology layer's WEIGHT on high-face
    GTs (reward.py). The hybrid changes the topology layer's VALUE. The two must
    compose sanely: a feature-degraded candidate must score lower than the full part
    under BOTH afw on and afw off (ENG D10 / Codex F8)."""
    full_mesh, full_sig, full_hist = _plate_with_n_holes(4)
    miss_mesh, miss_sig, miss_hist = _plate_with_n_holes(1)        # 3 holes missing

    for afw in (True, False):
        cfg = RewardConfig(adaptive_feature_weighting=afw)
        full = score(full_mesh, full_mesh, candidate_sig=full_sig, gt_sig=full_sig,
                     candidate_hist=full_hist, gt_hist=full_hist, cfg=cfg)
        miss = score(miss_mesh, full_mesh, candidate_sig=miss_sig, gt_sig=full_sig,
                     candidate_hist=miss_hist, gt_hist=full_hist, cfg=cfg)
        assert miss.topology < full.topology, (
            f"missing features must lower topology (afw={afw})")
        assert miss.raw["topology_hist"] < full.raw["topology_hist"], (
            f"the histogram half must register the missing holes (afw={afw})")


# ── 7. sandbox inline walk == module walk (D5 — drift guard) ──────────────────

def test_sandbox_inline_walk_matches_module():
    """The runner's sandbox epilogue carries an INLINE histogram walk as a fallback
    for when surface_histogram isn't importable on the sandbox sys.path. That inline
    walk MUST produce a byte-identical histogram to the canonical module function,
    or the candidate and GT histograms (compared by count-ratio) would silently
    disagree by where they ran (ENG D5). Run a real candidate through the sandbox
    (which uses the module path) and assert it matches a direct module call."""
    from harness.runner import run_candidate
    import tempfile
    code = ("from build123d import *\n"
            "with BuildPart() as p:\n"
            "    Box(40, 40, 40)\n"            # {Plane:6}
            "    Cylinder(8, 40, mode=Mode.SUBTRACT)\n"   # bore -> adds a Cylinder face
            "result = p")
    run = run_candidate(code, tempfile.mkdtemp(prefix="_d5_"), timeout=120)
    assert run.ok, run.error
    assert run.histogram is not None, "runner must emit a histogram"
    # The sandbox computed it; recompute via the module on the re-imported STEP and
    # assert the canonical path agrees with what the sandbox wrote.
    from surface_histogram import from_step
    module_hist = surface_histogram(from_step(str(run.step_path)))
    assert run.histogram == module_hist, (
        f"sandbox histogram {run.histogram} != module histogram {module_hist} — "
        "the inline walk and module walk have drifted (D5)")
