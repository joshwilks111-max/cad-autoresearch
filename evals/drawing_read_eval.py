"""
drawing_read_eval.py — score a drawing-read extraction against a hand-authored key.

This is the LLM eval the harness was missing (skill-pack component #4). The
deterministic referee in `harness/reward.py` grades *geometry*; nothing graded
whether the model READ THE DRAWING right. `drawing_extract.py` calls drawing-reading
"the single hardest open problem in AI-to-CAD" (Opus ~40%, Gemini ~77%) — so it is
the real bottleneck, and the thing most worth an eval.

DESIGN — offline and hermetic by default:
  * The scorer is PURE dict-in -> metrics-out. No network, no model call, no file I/O.
  * The pytest (`test_drawing_read_eval.py`) scores a FROZEN `extracted.json` (a recorded
    model output) against a hand-authored `expected_dims.json`. Both are derived from the
    drawing's *drawn callouts* (public design intent), NEVER from any `ground_truth/`.
  * Live extraction (which hits Gemini/Claude) lives behind RUN_LLM_EVALS=1 in the test,
    so `pytest` stays free and fast.

WHAT IT SCORES (three axes, each in [0,1]):
  1. dimension recall / precision — did the read recover the dimensions on the page?
     Two nominal values match when they agree within a relative+absolute tolerance
     (a 120 mm width read as 119.8 is correct; read as 90 is not).
  2. unit correctness — did it get the units right (the recurring inch->mm trap)?
  3. feature-count agreement — right number of holes/features, by polarity.

The headline `score` is recall-weighted (recall is what a missed callout costs a
reconstruction); the per-axis numbers are returned for diagnosis and for the
pre-registered bar (>= MIN_RECALL).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Pre-registered bar. A read at or above this recall is "good enough to model from".
MIN_RECALL = 0.8

# Two nominal lengths match within EITHER an absolute floor OR a relative band —
# the floor keeps small features (a 4 mm radius) from needing sub-micron agreement,
# the relative band keeps large features (a 400 mm length) from matching anything close.
_ABS_TOL_MM = 0.5
_REL_TOL = 0.02


def _nominals(extraction: dict, *, key: str = "nominal_mm") -> list[float]:
    """Pull every readable nominal length (mm) out of a schema-shaped extraction.

    Looks at dimensions[].nominal_mm AND feature diameters/depths, because a callout
    like "4 × Ø8" lives in features[], not dimensions[]. Bools/None skipped.
    """
    out: list[float] = []
    for d in extraction.get("dimensions", []) or []:
        if not isinstance(d, dict):
            continue
        # Angular dims are degrees, not lengths — they must never enter the mm length
        # pool. (A fixture/read storing an angle in `nominal_mm` would otherwise be
        # scaled x25.4 by normalize_to_mm — 90deg -> 2286 — and inflate the recall
        # denominator with a phantom "length". Skip by the sibling `type`.)
        if str(d.get("type", "")).lower() in ("angle", "angular"):
            continue
        v = d.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    for f in extraction.get("features", []) or []:
        if not isinstance(f, dict):
            continue
        for fk in ("diameter_mm", "depth_mm"):
            v = f.get(fk)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
    return out


def _values_match(a: float, b: float) -> bool:
    return abs(a - b) <= max(_ABS_TOL_MM, _REL_TOL * max(abs(a), abs(b)))


def _greedy_match(expected: list[float], got: list[float]) -> int:
    """Count how many expected values are matched by a distinct got value (greedy,
    one-to-one). Order-independent; each got value is consumed at most once."""
    remaining = list(got)
    hits = 0
    for e in expected:
        for i, g in enumerate(remaining):
            if _values_match(e, g):
                del remaining[i]
                hits += 1
                break
    return hits


def _feature_count(extraction: dict, *, polarity: str | None = None) -> int:
    """Total feature quantity (summing the `quantity` field; default 1 each).
    Optionally restrict to a polarity ('cut'/'add')."""
    total = 0
    for f in extraction.get("features", []) or []:
        if not isinstance(f, dict):
            continue
        if polarity is not None and f.get("polarity") != polarity:
            continue
        q = f.get("quantity", 1)
        total += int(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else 1
    return total


@dataclass
class EvalResult:
    recall: float                 # fraction of expected dims recovered
    precision: float              # fraction of read dims that were real
    unit_correct: bool            # did units match the expected
    feature_count_score: float    # 1 - normalized |Δ feature count|, in [0,1]
    expected_feature_count: int
    got_feature_count: int
    n_expected_dims: int
    n_matched_dims: int
    n_got_dims: int
    score: float                  # headline composite (recall-weighted)
    passed: bool                  # score gate AND recall gate AND units
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "unit_correct": self.unit_correct,
            "feature_count_score": round(self.feature_count_score, 4),
            "expected_feature_count": self.expected_feature_count,
            "got_feature_count": self.got_feature_count,
            "n_expected_dims": self.n_expected_dims,
            "n_matched_dims": self.n_matched_dims,
            "n_got_dims": self.n_got_dims,
            "score": round(self.score, 4),
            "passed": self.passed,
            "notes": self.notes,
        }


def score_extraction(expected: dict, got: dict) -> EvalResult:
    """Score one extraction (`got`) against the hand-authored key (`expected`).

    Both are schema-shaped dicts (the `drawing_extract.EMPTY_SCHEMA` shape). Pure:
    no I/O, no network, deterministic. The `expected` is the answer key derived from
    the drawing's drawn callouts; `got` is a model's (frozen or live) read.
    """
    notes: list[str] = []

    exp_dims = _nominals(expected)
    got_dims = _nominals(got)
    n_exp = len(exp_dims)
    n_got = len(got_dims)
    matched = _greedy_match(exp_dims, got_dims)

    recall = matched / n_exp if n_exp else 1.0
    precision = matched / n_got if n_got else (1.0 if n_exp == 0 else 0.0)

    exp_units = str(expected.get("units", "unknown")).lower()
    got_units = str(got.get("units", "unknown")).lower()
    unit_correct = exp_units == got_units
    if not unit_correct:
        notes.append(f"unit mismatch: expected {exp_units!r}, got {got_units!r}")

    exp_fc = _feature_count(expected)
    got_fc = _feature_count(got)
    # normalized agreement: 1 when equal, decaying with the relative miscount.
    denom = max(exp_fc, 1)
    feature_count_score = max(0.0, 1.0 - abs(exp_fc - got_fc) / denom)
    if exp_fc != got_fc:
        notes.append(f"feature-count mismatch: expected {exp_fc}, got {got_fc}")

    missed = n_exp - matched
    if missed:
        notes.append(f"{missed}/{n_exp} expected dimension(s) not recovered")
    spurious = n_got - matched
    if spurious > 0:
        notes.append(f"{spurious} read dimension(s) matched nothing expected")

    # Headline: recall dominates (a missed callout breaks a reconstruction), with a
    # unit-correctness gate folded in (wrong units invalidate every number) and a
    # smaller feature-count contribution.
    base = 0.7 * recall + 0.3 * feature_count_score
    score = base * (1.0 if unit_correct else 0.5)

    passed = (score >= 0.0) and (recall >= MIN_RECALL) and unit_correct
    # (the score>=0.0 is a placeholder for an explicit score bar if one is added;
    #  the load-bearing gates are recall>=MIN_RECALL and unit_correct.)

    return EvalResult(
        recall=recall,
        precision=precision,
        unit_correct=unit_correct,
        feature_count_score=feature_count_score,
        expected_feature_count=exp_fc,
        got_feature_count=got_fc,
        n_expected_dims=n_exp,
        n_matched_dims=matched,
        n_got_dims=n_got,
        score=score,
        passed=passed,
        notes=notes,
    )
