"""
test_drawing_read_eval.py — pytest for the offline drawing-read LLM eval.

OFFLINE BY DEFAULT. The default test run (`pytest evals/`) scores FROZEN extractions
against hand-authored keys — no network, no model call, fast and free. It asserts:
  * the good frozen read PASSES the pre-registered bar (recall >= MIN_RECALL, units ok);
  * the canary BAD read FAILS (catches the inch-trap + dropped callouts);
  * the scorer's matcher/units/feature-count behave (focused unit checks).

LIVE PATH. The single live test (real extraction via Gemini/Claude) is gated behind
the RUN_LLM_EVALS=1 env var, so it never runs in the normal/CI suite. Refresh a frozen
fixture with:
    RUN_LLM_EVALS=1 .venv/Scripts/python.exe drawing_extract.py \
        --drawing tasks/trial_lbracket/drawing.png --json \
        > evals/fixtures/trial_lbracket/extracted.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Import the scorer. evals/ is a sibling of the repo root tools; add repo root so the
# `drawing_read_eval` module (next to this file) and `drawing_extract` (repo root) both
# import whether pytest is run from the repo root or from evals/.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
import sys
for _p in (str(_HERE), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drawing_read_eval import MIN_RECALL, score_extraction  # noqa: E402

FIX = _HERE / "fixtures" / "trial_lbracket"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# --------------------------------------------------------------------------- #
# Offline: the good frozen read passes the bar
# --------------------------------------------------------------------------- #
def test_good_frozen_read_passes_bar():
    expected = _load("expected_dims.json")
    got = _load("extracted.json")
    res = score_extraction(expected, got)
    # diagnostic on failure
    assert res.passed, f"good fixture should pass: {res.as_dict()}"
    assert res.recall >= MIN_RECALL, f"recall {res.recall} below bar {MIN_RECALL}"
    assert res.unit_correct, "units should match (both mm)"
    # it is a realistic read, not a rigged perfect one
    assert res.recall < 1.0, "frozen fixture intentionally models one missed callout"


# --------------------------------------------------------------------------- #
# Offline: the canary BAD read fails (the eval has teeth)
# --------------------------------------------------------------------------- #
def test_canary_bad_read_fails():
    expected = _load("expected_dims.json")
    bad = _load("extracted_canary_bad.json")
    res = score_extraction(expected, bad)
    assert not res.passed, f"canary must FAIL the bar, got {res.as_dict()}"


def test_canary_trips_on_unit_trap():
    """The canary misreads mm as inches — unit_correct must be False on its own."""
    expected = _load("expected_dims.json")
    bad = _load("extracted_canary_bad.json")
    res = score_extraction(expected, bad)
    assert not res.unit_correct, "inch-misread must be caught by the unit axis"


def test_canary_trips_on_dropped_callouts():
    """Independently of units, dropping >half the dimensions must crater recall."""
    expected = _load("expected_dims.json")
    bad = _load("extracted_canary_bad.json")
    # neutralize the unit failure to isolate the recall failure
    bad_units_fixed = dict(bad, units="mm")
    res = score_extraction(expected, bad_units_fixed)
    assert res.recall < MIN_RECALL, f"dropped callouts should fail recall, got {res.recall}"


# --------------------------------------------------------------------------- #
# Offline: focused scorer behavior (the matcher / tolerance / feature count)
# --------------------------------------------------------------------------- #
def test_self_score_is_perfect():
    """Scoring the expected against itself is a recall=1.0, unit-correct pass."""
    expected = _load("expected_dims.json")
    res = score_extraction(expected, expected)
    assert res.recall == 1.0 and res.precision == 1.0 and res.unit_correct
    assert res.feature_count_score == 1.0


def test_tolerance_band_accepts_small_drift():
    """A 120.0 expected read as 119.8 (within band) still matches."""
    expected = {"units": "mm", "dimensions": [{"nominal_mm": 120.0}], "features": []}
    got = {"units": "mm", "dimensions": [{"nominal_mm": 119.8}], "features": []}
    res = score_extraction(expected, got)
    assert res.recall == 1.0, "0.2mm drift on 120mm is within the tolerance band"


def test_tolerance_band_rejects_confusing_spacing_for_extent():
    """A 60mm depth read as 36mm (a different drawn callout) must NOT match."""
    expected = {"units": "mm", "dimensions": [{"nominal_mm": 60.0}], "features": []}
    got = {"units": "mm", "dimensions": [{"nominal_mm": 36.0}], "features": []}
    res = score_extraction(expected, got)
    assert res.recall == 0.0, "60 vs 36 are distinct callouts, must not match"


def test_feature_count_mismatch_penalized():
    expected = _load("expected_dims.json")          # 4 + 2 = 6 holes
    got = _load("extracted.json")
    base = score_extraction(expected, got)
    assert base.expected_feature_count == 6
    # drop a hole group -> feature-count score must drop
    fewer = dict(got, features=got["features"][:1])  # only the 4-hole group
    res = score_extraction(expected, fewer)
    assert res.got_feature_count == 4
    assert res.feature_count_score < base.feature_count_score


# --------------------------------------------------------------------------- #
# LIVE path — real extraction, gated. Never runs in the default/CI suite.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    os.environ.get("RUN_LLM_EVALS") != "1",
    reason="live drawing extraction is gated behind RUN_LLM_EVALS=1 (network + model call)",
)
def test_live_extraction_meets_bar():
    """Run the REAL drawing reader on the drawing and score it. Costs a model call;
    only runs under RUN_LLM_EVALS=1. Proves the live path is wired and clears the bar."""
    from drawing_extract import extract_drawing  # imported lazily so offline never needs it

    drawing = _REPO / "tasks" / "trial_lbracket" / "drawing.png"
    assert drawing.exists(), f"missing drawing fixture: {drawing}"
    expected = _load("expected_dims.json")

    got = extract_drawing(str(drawing), backend="auto")
    res = score_extraction(expected, got)
    # Live reads are noisier than the frozen stand-in; assert the pre-registered bar,
    # and surface the full breakdown for triage when it misses.
    assert res.recall >= MIN_RECALL, (
        f"live read below recall bar {MIN_RECALL}: {res.as_dict()}\n"
        f"extraction={json.dumps(got, indent=2)[:1500]}"
    )
