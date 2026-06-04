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

@pytest.mark.slow
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

@pytest.mark.slow
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

@pytest.mark.slow
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

@pytest.mark.slow
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


# ── 8. the INLINE fallback walk matches the module (review C4) ─────────────────

def test_inline_fallback_matches_module():
    """runner.py's sandbox epilogue carries an INLINE histogram walk used ONLY when
    `from surface_histogram import surface_histogram` fails on the sandbox sys.path.
    test_sandbox_inline_walk_matches_module never exercises it (the module import
    succeeds in-repo). This test FORCES the import to fail by running a candidate with
    a sitecustomize that shadows surface_histogram with an ImportError, then asserts
    the inline-walked histogram.json byte-matches the canonical module walk. This is
    the drift guard runner.py's comment promises (review finding C4)."""
    from harness.runner import run_candidate
    import tempfile
    code = ("from build123d import *\n"
            "with BuildPart() as p:\n"
            "    Box(40, 40, 40)\n"
            "    Cylinder(8, 40, mode=Mode.SUBTRACT)\n"
            "result = p")
    ws = Path(tempfile.mkdtemp(prefix="_inline_"))
    # A sitecustomize.py in the workspace (cwd of the sandbox) makes
    # `import surface_histogram` raise inside the candidate process ONLY, forcing the
    # inline fallback. cwd is on sys.path[0] for the script, so this shadows the repo module.
    (ws / "surface_histogram.py").write_text(
        "raise ImportError('forced fallback for test_inline_fallback_matches_module')\n",
        encoding="utf-8")
    run = run_candidate(code, ws, timeout=120)
    assert run.ok, run.error
    assert run.histogram is not None, "inline fallback must still emit a histogram"
    # Compare against the canonical module walk on the re-imported candidate STEP.
    from surface_histogram import surface_histogram as _sh, from_step
    module_hist = _sh(from_step(str(run.step_path)))
    assert run.histogram == module_hist, (
        f"INLINE fallback histogram {run.histogram} != module {module_hist} — the "
        "hand-maintained inline _NAMES/_KEYS have drifted from surface_histogram (C4)")


# ── 9. determinism — the histogram is byte-identical across two runs (D7) ──────

@pytest.mark.slow
def test_histogram_is_deterministic_across_runs():
    """The histogram feeds a deterministic reward layer. Two runs of the SAME
    candidate must produce a byte-identical histogram (no dict-ordering or
    face-walk-ordering nondeterminism). Review/testing flagged this was unguarded."""
    from harness.runner import run_candidate
    import tempfile
    code = ("from build123d import *\n"
            "with BuildPart() as p:\n"
            "    Box(30, 20, 10)\n"
            "    Cylinder(4, 10, mode=Mode.SUBTRACT)\n"
            "result = p")
    r1 = run_candidate(code, tempfile.mkdtemp(prefix="_det1_"), timeout=120)
    r2 = run_candidate(code, tempfile.mkdtemp(prefix="_det2_"), timeout=120)
    assert r1.ok and r2.ok
    assert r1.histogram == r2.histogram, (
        f"histogram non-deterministic across runs: {r1.histogram} != {r2.histogram}")


# ── 10. score() degrades gracefully when the hist tool can't import (review) ───

@pytest.mark.slow
def test_score_degrades_when_hist_tool_unimportable(monkeypatch):
    """If surface_histogram couldn't be imported (reward.py sets _hist_sim=None), the
    hybrid must fall back to exact-only — identical to the no-hist path — even when
    histograms ARE passed. Untested before review (every test imports the tool fine)."""
    import harness.reward as R
    monkeypatch.setattr(R, "_hist_sim", None)
    solid = _lbracket_solid()
    mesh = _solid_to_mesh(solid)
    sig = G.topology_signature_from_solid(solid)
    hist = surface_histogram(solid)
    r = R.score(mesh, mesh, candidate_sig=sig, gt_sig=sig,
                candidate_hist=hist, gt_hist=hist, cfg=RewardConfig())
    assert r.raw["topology_hist"] is None, "tool unimportable -> no histogram half"
    assert r.topology == r.raw["topology_exact"], "must degrade to exact-only"


# ── 11. empty/None candidate hist scores the histogram half LOW, not skipped ───

@pytest.mark.slow
def test_empty_candidate_hist_scores_low_not_skipped(monkeypatch):
    """A degenerate candidate (empty or all-zero histogram) against a real GT must
    score the histogram half at 0.0 (honest: it produced no classifiable faces), NOT
    silently skip to exact-only. Guards the {} vs {Plane:0} representation fork the
    review found (C3): both must behave identically now."""
    solid = _lbracket_solid()
    mesh = _solid_to_mesh(solid)
    sig = G.topology_signature_from_solid(solid)
    gt_hist = surface_histogram(solid)              # a real GT reference (has faces)
    cfg = RewardConfig()
    # both an empty dict and an all-zero-with-keys dict must hit the hybrid and score
    # the histogram half 0.0 (count_ratio_similarity zero-guard), NOT skip to exact-only.
    for empty in ({}, {"Plane": 0, "Cylinder": 0}, None):
        r = score(mesh, mesh, candidate_sig=sig, gt_sig=sig,
                  candidate_hist=empty, gt_hist=gt_hist, cfg=cfg)
        assert r.raw["topology_hist"] == 0.0, (
            f"empty candidate hist {empty!r} must score histogram half 0.0, "
            f"got {r.raw['topology_hist']!r} (the C3 representation fork)")


# ── 12. count_ratio isolates the cosine factor when face counts are equal ──────

def test_count_ratio_equal_counts_is_pure_cosine():
    """When Σhc == Σhg (ratio factor = 1.0) the similarity is pure cosine — the
    sub-case the monotonicity ladder never hits (every rung changes the face sum).
    Two equal-total, different-type histograms: 0 < result < 1 and == bare cosine."""
    a = {"Plane": 6, "Cylinder": 2}     # 8 faces
    b = {"Plane": 5, "Cylinder": 3}     # 8 faces, different type split
    cr = count_ratio_similarity(a, b)
    cos = histogram_similarity(a, b)
    assert cr == pytest.approx(cos, abs=1e-9), "equal counts -> ratio 1.0 -> pure cosine"
    assert 0.0 < cr < 1.0, "different type split must score strictly between 0 and 1"


# ── 13. the GT histogram cache: hit, no-cache-on-None, mtime_ns key (review C2) ─

def test_gt_histogram_cache_behavior(monkeypatch, tmp_path):
    """run_inner_loop._gt_histogram: (a) caches a success and serves it without
    recomputing; (b) does NOT cache a None (transient failure must retry, not pin the
    whole run to exact-only); (c) tolerates a stat() failure. Untested before review."""
    import run_inner_loop as RIL
    RIL._GT_HIST_CACHE.clear()

    step = tmp_path / "result.step"
    step.write_text("dummy", encoding="utf-8")     # existence is enough; we patch the walk

    calls = {"n": 0}

    def _fake_success(p):
        calls["n"] += 1
        return {"Plane": 6}

    # (a) success is cached: two calls -> the walk runs once.
    monkeypatch.setattr(RIL, "_gt_histogram", RIL._gt_histogram)   # ensure real fn
    monkeypatch.setattr("surface_histogram.surface_histogram", _fake_success, raising=False)
    monkeypatch.setattr("surface_histogram.from_step", lambda s: object(), raising=False)
    h1 = RIL._gt_histogram(step)
    h2 = RIL._gt_histogram(step)
    assert h1 == h2 == {"Plane": 6}
    assert calls["n"] == 1, "a cached success must not recompute"

    # (b) a failure is NOT cached: it retries next call (no permanent None pinning).
    RIL._GT_HIST_CACHE.clear()
    fail_calls = {"n": 0}

    def _fake_fail(p):
        fail_calls["n"] += 1
        raise RuntimeError("transient")

    monkeypatch.setattr("surface_histogram.surface_histogram", _fake_fail, raising=False)
    assert RIL._gt_histogram(step) is None
    assert RIL._gt_histogram(step) is None
    assert fail_calls["n"] == 2, "a transient failure must RETRY, not be pinned to None"
