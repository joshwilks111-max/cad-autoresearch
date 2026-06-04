#!/usr/bin/env python3
"""drawing_read_ab.py -- the drawing-READ A/B (Opus vs scaffold-floor).

Runs the drawing-read backends on each part that has a TRUSTWORTHY hand-authored fixture,
scores every read OFFLINE against that fixture, and prints a per-part recall table vs the
pre-registered 0.8 bar. The DEFAULT A/B is the project reader -- Opus on the Claude
subscription -- against the scaffold (read-nothing) floor: "how well does the model we
actually use read these NIST drawings?". This is the FIRST measurement on these specific
parts; the literature prior (Opus ~40% dimension recall) is the thing being TESTED, not
confirmed.

The metered Gemini-VISION read arm is OFF by default (it bills a separate Google plane and
is not part of the subscription workflow). Pass `--backends gemini claude scaffold` to add it
if you have a funded Google key. NB: this is the Gemini *reading* path -- distinct from the
Gemini image-GENERATION (Nano Banana) tool, which this experiment does not touch.

Design choices that make the result honest:
  * PINNED backends (no 'auto'/'discover' in the loop) so we never spend extra probe calls
    and never silently fall through gemini->claude->scaffold mid-measurement.
  * The claude arm is pinned to --model opus (drawing_extract finding #3 fix) and the
    resolved model is recorded, so the "Opus arm" provably ran Opus.
  * A read that truncated at MAX_TOKENS is flagged TRUNCATED and NOT scored as honest-low
    recall -- it is a tooling artifact, not a model failure.
  * scaffold is the FREE FLOOR control: an empty schema. Its recall is what "read nothing"
    scores, so any backend at/below the scaffold line added no signal.
  * Scoring is offline/free via evals/drawing_read_eval.score_extraction.

Billing: gemini = metered Google plane (~/.banana key). claude = Anthropic SUBSCRIPTION via
`claude -p` OAuth (drawing_extract scrubs ANTHROPIC_API_KEY). Keep ANTHROPIC_API_KEY unset.

Usage:
  .venv/Scripts/python.exe evals/drawing_read_ab.py            # all fixtured parts
  .venv/Scripts/python.exe evals/drawing_read_ab.py --parts nist_ctc_03 nist_ftc_07
  .venv/Scripts/python.exe evals/drawing_read_ab.py --json results.json   # also dump JSON
  .venv/Scripts/python.exe evals/drawing_read_ab.py --backends gemini scaffold  # subset
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
for _p in (str(_HERE), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drawing_extract import extract_drawing, normalize_extraction  # noqa: E402
from drawing_read_eval import MIN_RECALL, _nominals, score_extraction  # noqa: E402

FIXTURES_DIR = _HERE / "fixtures"
TASKS_DIR = _REPO / "tasks"
# Default A/B: the project reader (Opus on the Claude subscription) vs the read-nothing FLOOR.
# The metered Gemini-vision arm is intentionally OFF by default — pass --backends gemini ...
# to include it if you have a funded Google key. This keeps the A/B on the subscription plane.
DEFAULT_BACKENDS = ("claude", "scaffold")


def fixtured_parts() -> list[str]:
    """Parts that have a drawing.png AND a NON-EMPTY expected_dims.json.
    trial_lbracket is excluded here -- it is the unit-test exemplar, not a NIST read part.

    The non-empty check is load-bearing: an empty/dead fixture (no readable nominals) makes
    score_extraction return recall==1.0 by vacuous truth (`recall = matched / n_exp if n_exp
    else 1.0`), so a part with a dead key would silently report PASS against nothing. We drop
    any fixture whose nominal pool is empty so the A/B never scores against a useless key.
    """
    out = []
    for key in sorted(FIXTURES_DIR.glob("*/expected_dims.json")):
        part = key.parent.name
        if part == "trial_lbracket":
            continue
        if not (TASKS_DIR / part / "drawing.png").exists():
            continue
        try:
            fixture = json.loads(key.read_text(encoding="utf-8"))
        except Exception:
            continue  # malformed JSON -> not a usable fixture
        if len(_nominals(fixture)) < 1:
            continue  # dead key: no readable dimensions/diameters -> would score vacuous 1.0
        out.append(part)
    return out


def _is_truncated(extraction: dict) -> bool:
    detail = str(extraction.get("_backend_detail", ""))
    warnings = " ".join(extraction.get("_warnings", []))
    return "TRUNCATED" in detail or "MAX_TOKENS" in warnings


def run_one(part: str, backend: str) -> dict:
    """Run one (part, backend) read and score it against the part's fixture.

    UNITS: the fixture is authored AS DRAWN, pre-normalization (e.g. inches: Ø.438 -> 0.438).
    `extract_drawing` ALWAYS runs `normalize_to_mm` on a read, so a backend that reads inches
    returns mm (0.438 -> 11.1252). Scoring a pre-normalization fixture against a post-
    normalization read is a units mismatch that craters recall to 0 even on a PERFECT read.
    Fix: normalize the fixture through the SAME pipeline before scoring, so both sides live in
    mm and a correct inch read matches the inch fixture. This is the apples-to-apples space.
    """
    drawing = TASKS_DIR / part / "drawing.png"
    fixture = json.loads((FIXTURES_DIR / part / "expected_dims.json").read_text(encoding="utf-8"))
    fixture_mm = normalize_extraction(fixture)  # inch fixture -> mm, same space as the read

    extraction = extract_drawing(str(drawing), backend=backend)
    res = score_extraction(fixture_mm, extraction)
    truncated = _is_truncated(extraction)
    return {
        "part": part,
        "backend": backend,
        "resolved_model": extraction.get("_backend_detail"),
        "recall": round(res.recall, 4),
        "precision": round(res.precision, 4),
        "unit_correct": res.unit_correct,
        "feature_count_score": round(res.feature_count_score, 4),
        "n_expected_dims": res.n_expected_dims,
        "n_matched_dims": res.n_matched_dims,
        "n_got_dims": res.n_got_dims,
        "passed_bar": (res.recall >= MIN_RECALL) and res.unit_correct and not truncated,
        "truncated": truncated,
        "notes": res.notes,
        "extraction_units": extraction.get("units"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Drawing-read A/B (Gemini vs Opus vs scaffold).")
    ap.add_argument("--parts", nargs="*", default=None,
                    help="part ids (default: every fixtured NIST part)")
    ap.add_argument("--backends", nargs="*", default=list(DEFAULT_BACKENDS),
                    help=f"backends (default: {' '.join(DEFAULT_BACKENDS)})")
    ap.add_argument("--json", metavar="PATH", default=None,
                    help="also write the full results array to this JSON path")
    args = ap.parse_args(argv)

    parts = args.parts or fixtured_parts()
    if not parts:
        print("no fixtured parts found; author evals/fixtures/<id>/expected_dims.json first",
              file=sys.stderr)
        return 2

    n_paid_gemini = len(parts) if "gemini" in args.backends else 0
    n_paid_claude = len(parts) if "claude" in args.backends else 0
    print(f"== drawing-read A/B ==  parts={parts}  backends={args.backends}")
    print(f"   bar=recall>={MIN_RECALL}  expected paid calls: "
          f"gemini~{n_paid_gemini} (max {n_paid_gemini * 8} w/ fallbacks), "
          f"claude={n_paid_claude} subscription turns, scaffold=0\n")

    results: list[dict] = []
    for part in parts:
        for backend in args.backends:
            r = run_one(part, backend)
            results.append(r)
            flag = ""
            if r["truncated"]:
                flag = "  [TRUNCATED -- not scored as honest-low]"
            elif r["passed_bar"]:
                flag = "  PASS"
            mdl = r["resolved_model"] or "-"
            # flush per read: a real Opus turn is minutes long and stdout is buffered when
            # redirected to a file, so without flush the progress is invisible until exit.
            print(f"  {part:14s} {backend:9s} recall={r['recall']:.3f} "
                  f"({r['n_matched_dims']}/{r['n_expected_dims']})  units={r['extraction_units']}  "
                  f"model={mdl}{flag}", flush=True)
        print(flush=True)

    # compact per-part summary table
    print("== per-part recall vs 0.8 bar ==")
    by_part: dict[str, dict] = {}
    for r in results:
        by_part.setdefault(r["part"], {})[r["backend"]] = r
    header = f"{'part':14s} " + " ".join(f"{b:>10s}" for b in args.backends)
    print(header)
    print("-" * len(header))
    for part in parts:
        row = f"{part:14s} "
        for b in args.backends:
            r = by_part[part].get(b)
            cell = f"{r['recall']:.3f}" + ("T" if r and r["truncated"] else "") if r else "-"
            row += f"{cell:>10s} "
        print(row)

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
