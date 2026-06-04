"""
test_fixtures_discovered.py — make every authored fixture RUN (review finding #2).

THE FALSE-GREEN BUG. `test_drawing_read_eval.py` hardcodes
`FIX = fixtures/"trial_lbracket"`, so any NEW `evals/fixtures/<id>/expected_dims.json`
exercises NOTHING — pytest stays green by IGNORING it. Authoring a fixture without a
test that discovers it is a no-op. This module GLOBS every fixture and asserts each one
is well-formed and self-consistent, so a new part is covered the moment its key lands.

For each `evals/fixtures/*/expected_dims.json` it asserts:
  * it parses as JSON and matches the EMPTY_SCHEMA shape (same keys, right types);
  * scoring it against ITSELF yields recall == 1.0 and unit_correct (a sanity floor —
    a malformed key that can't even score itself perfectly is broken);
  * it carries the `_comment` provenance line (the page-only-authorship assertion);
  * it has at least one readable numeric value (an all-empty key would score recall 0
    against any real model read and silently pass the eval — that is a dead fixture).

Discovery is dynamic: drop a new fixture dir in and it is tested automatically. The test
COUNT going up by the number of new fixtures is the proof they are discovered, not ignored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
for _p in (str(_HERE), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drawing_extract import EMPTY_SCHEMA  # noqa: E402
from drawing_read_eval import MIN_RECALL, _nominals, score_extraction  # noqa: E402

FIXTURES_DIR = _HERE / "fixtures"

# Every fixture dir that ships an expected_dims.json is discovered here.
_FIXTURE_KEYS = sorted(FIXTURES_DIR.glob("*/expected_dims.json"))
_FIXTURE_IDS = [p.parent.name for p in _FIXTURE_KEYS]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_at_least_the_known_fixtures_are_discovered():
    """Guard against a broken glob silently discovering zero fixtures (which would make
    every parametrized test below vacuously pass).

    The drawing-read parts whose NIST renders are legible enough to author a TRUSTWORTHY
    clean-room key: ctc_03, ftc_07, ftc_09 (read by tile-cropping a 500-DPI render). The
    other two assets (ctc_05, stc_06) are DELIBERATELY without a fixture this phase — their
    available renders lack the contrast/legibility for a reliable page-only read, and a
    hallucinated answer-key would corrupt the A/B it is meant to score. See
    docs/experiments/drawing-read-opus-vs-scaffold.md for the legibility triage.
    """
    found = set(_FIXTURE_IDS)
    must_have = {"trial_lbracket", "nist_ctc_03", "nist_ftc_07", "nist_ftc_09"}
    missing = must_have - found
    assert not missing, f"expected fixtures missing: {sorted(missing)} (found {sorted(found)})"


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_fixture_parses_and_matches_schema_shape(key_path: Path):
    data = _load(key_path)
    assert isinstance(data, dict), f"{key_path} is not a JSON object"
    # every EMPTY_SCHEMA top-level key (minus the module-private provenance keys) present
    required = set(EMPTY_SCHEMA) - {"_backend", "_backend_detail", "_warnings"}
    missing = required - set(data)
    assert not missing, f"{key_path.parent.name}: missing schema keys {sorted(missing)}"
    assert isinstance(data["dimensions"], list)
    assert isinstance(data["features"], list)
    assert isinstance(data["gdt_frames"], list)
    assert isinstance(data["title_block"], dict)


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_fixture_self_scores_perfectly(key_path: Path):
    """A well-formed key scored against itself is recall==1.0, unit-correct (sanity)."""
    data = _load(key_path)
    res = score_extraction(data, data)
    assert res.recall == 1.0, (
        f"{key_path.parent.name}: self-score recall={res.recall} != 1.0 "
        f"({res.as_dict()})"
    )
    assert res.unit_correct, f"{key_path.parent.name}: self-score not unit-correct"
    assert res.precision == 1.0, f"{key_path.parent.name}: self-score precision != 1.0"


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_fixture_has_readable_values(key_path: Path):
    """An all-empty key scores recall 0 vs any real read and silently 'passes' the eval —
    a dead fixture. Every authored key must carry >=1 readable numeric value."""
    data = _load(key_path)
    nominals = _nominals(data)
    assert len(nominals) >= 1, (
        f"{key_path.parent.name}: no readable dimensions/diameters — dead fixture "
        f"(dimensions={len(data['dimensions'])}, features={len(data['features'])})"
    )


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_fixture_carries_provenance_comment(key_path: Path):
    """The _comment must assert page-only authorship (the GT-safety contract)."""
    data = _load(key_path)
    comment = str(data.get("_comment", "")).lower()
    assert comment, f"{key_path.parent.name}: missing _comment provenance line"
    # it must reference the drawing/page and disclaim ground_truth
    assert ("drawing" in comment or "page" in comment), (
        f"{key_path.parent.name}: _comment does not cite the drawing/page as the source"
    )
    assert "ground_truth" in comment or "ground truth" in comment, (
        f"{key_path.parent.name}: _comment does not disclaim ground_truth provenance"
    )


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_fixture_units_are_valid(key_path: Path):
    """Units must be one of the schema's allowed values (catches a typo like 'inch')."""
    data = _load(key_path)
    assert data["units"] in ("mm", "in", "unknown"), (
        f"{key_path.parent.name}: units={data['units']!r} not in mm|in|unknown"
    )


@pytest.mark.parametrize("key_path", _FIXTURE_KEYS, ids=_FIXTURE_IDS)
def test_no_angle_pollutes_the_length_recall_pool(key_path: Path):
    """The /review MEDIUM: an angular dim (type='angle') must NOT enter the mm length
    recall pool. If it did, normalize_to_mm would scale e.g. 90deg x25.4 -> 2286 and
    inflate the recall denominator with a phantom 'length', so a perfect read could
    miss the bar on the answer-key's own units artifact. _nominals must drop angles."""
    from drawing_extract import normalize_extraction  # noqa: E402
    data = _load(key_path)
    has_angle = any(
        isinstance(d, dict) and str(d.get("type", "")).lower() in ("angle", "angular")
        for d in data.get("dimensions", [])
    )
    pool = _nominals(normalize_extraction(data))
    # no value in the length pool may be an implausibly-scaled angle (>= 360 mm only
    # appears here if a degree value was scaled; real callouts on these parts are < 360mm)
    assert all(v < 360.0 for v in pool), (
        f"{key_path.parent.name}: length pool has a scaled-angle artifact: "
        f"{[v for v in pool if v >= 360.0]} (has_angle_dim={has_angle})"
    )
