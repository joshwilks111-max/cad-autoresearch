#!/usr/bin/env python3
"""
trial.py — record + aggregate the human-vs-AI time trial (see PROTOCOL.md).

The trial has two competitors (`human`, `ai`) and rounds (`build` = first-pass model,
`revision` = the dimensional change request). For each (competitor, round) we record:
  - the submitted STEP, graded through the SAME B-rep referee as everything else
    (timetrial/grade_step.py's path: import_step -> topology_signature_from_solid ->
    score), so human and AI scores are commensurable;
  - turns-to-verified (PRIMARY metric — deterministic, counted from the ledger);
  - wall-clock seconds (SECONDARY — start/stop you pass in; for the AI this is
    end-to-end session time incl. inference, NOT a sum of CAD-build seconds).

PURE w.r.t. the harness: never mutates tasks/<id>/best_candidate.py or .best_score,
never touches runs/manual. Writes only under timetrial/.

Subcommands:
  record    log one (competitor, round) result + grade its STEP
  aggregate read timetrial/results.jsonl -> print + write the RESULTS table fragment
  verify    re-grade every recorded STEP from disk; assert scores reproduce + the
            honest-story checks (AI <= human turns/time on the build round, both
            sides >= the verified bar). Nonzero exit if the trial isn't honest.

Examples:
  python timetrial/trial.py record --competitor human --round build \\
      --task trial_lbracket --step submissions/human_build.step \\
      --turns 1 --seconds 540 --ts-start 2026-06-01T16:00:00
  python timetrial/trial.py record --competitor ai --round build \\
      --task trial_lbracket --step submissions/ai_build.step \\
      --turns 4 --seconds 260 --ts-start 2026-06-01T16:20:00
  python timetrial/trial.py aggregate
  python timetrial/trial.py verify --bar 0.95
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RESULTS = HERE / "results.jsonl"
GRADE_STEP = HERE / "grade_step.py"
PY = sys.executable


def _grade(task: str, step: str) -> dict:
    """Grade a STEP via grade_step.py --json (the one referee path). Returns its dict."""
    proc = subprocess.run(
        [PY, str(GRADE_STEP), "--task", task, "--step", step, "--json"],
        capture_output=True, text=True, cwd=str(REPO))
    line = (proc.stdout.strip().splitlines() or [""])[-1]
    try:
        return json.loads(line)
    except Exception:
        return {"ok": False, "error": f"grade_step failed: {proc.stderr.strip()[:300]}",
                "stdout": proc.stdout.strip()[:300]}


def cmd_record(a):
    g = _grade(a.task, a.step)
    rec = {
        "competitor": a.competitor, "round": a.round, "task": a.task,
        "step": a.step, "turns": a.turns, "seconds": a.seconds,
        "ts_start": a.ts_start, "note": a.note or "",
        "composite": g.get("composite"), "graded": g,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    if g.get("ok"):
        print(f"recorded {a.competitor}/{a.round}: composite={g['composite']:.4f} "
              f"turns={a.turns} seconds={a.seconds}")
    else:
        print(f"recorded {a.competitor}/{a.round}: GRADE FAILED — {g.get('error')}",
              file=sys.stderr)


def _load() -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _latest(rows, competitor, rnd):
    """Last recorded result for a (competitor, round)."""
    matches = [r for r in rows if r["competitor"] == competitor and r["round"] == rnd]
    return matches[-1] if matches else None


def cmd_aggregate(a):
    rows = _load()
    if not rows:
        print("no results recorded yet (timetrial/results.jsonl empty).")
        return
    lines = ["| Round | Competitor | Verified score | Turns | Wall-clock (s) |",
             "|---|---|---|---|---|"]
    for rnd in ("build", "revision"):
        for comp in ("human", "ai"):
            r = _latest(rows, comp, rnd)
            if not r:
                continue
            c = r.get("composite")
            lines.append(f"| {rnd} | {comp} | {c:.4f} | {r['turns']} | {r['seconds']} |"
                         if c is not None else
                         f"| {rnd} | {comp} | (ungraded) | {r['turns']} | {r['seconds']} |")
    table = "\n".join(lines)
    # headline computed from data (never hand-typed)
    hb, ab = _latest(rows, "human", "build"), _latest(rows, "ai", "build")
    headline = ""
    if hb and ab and hb["seconds"] and ab["seconds"]:
        ratio = hb["seconds"] / ab["seconds"]
        headline = (f"\nHeadline (build round): AI reached a referee-verified-correct "
                    f"solid in {ab['seconds']}s / {ab['turns']} turns vs the human's "
                    f"{hb['seconds']}s / {hb['turns']} turns — {ratio:.1f}x wall-clock.")
    print(table)
    if headline:
        print(headline)
    (HERE / "results_table.md").write_text(table + "\n" + headline + "\n")
    print(f"\n[wrote {HERE / 'results_table.md'}]")


def cmd_verify(a):
    rows = _load()
    if not rows:
        print("VERIFY: no results to check.", file=sys.stderr)
        sys.exit(2)
    ok = True
    # 1) every recorded STEP re-grades to (approx) its recorded composite
    for r in rows:
        if r.get("composite") is None:
            continue
        g = _grade(r["task"], r["step"])
        if not g.get("ok"):
            print(f"VERIFY FAIL: {r['competitor']}/{r['round']} no longer grades: "
                  f"{g.get('error')}")
            ok = False
            continue
        drift = abs(g["composite"] - r["composite"])
        status = "ok" if drift <= 1e-3 else "DRIFT"
        if drift > 1e-3:
            ok = False
        print(f"  re-grade {r['competitor']}/{r['round']}: {g['composite']:.4f} "
              f"(recorded {r['composite']:.4f}, drift {drift:.4f}) {status}")
    # 2) honest-story checks on the build round
    hb, ab = _latest(rows, "human", "build"), _latest(rows, "ai", "build")
    if hb and ab:
        for who, r in (("human", hb), ("ai", ab)):
            if r.get("composite") is not None and r["composite"] < a.bar:
                print(f"VERIFY FAIL: {who} build composite {r['composite']:.3f} "
                      f"< verified bar {a.bar}")
                ok = False
    print("VERIFY: PASS" if ok else "VERIFY: FAIL")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record")
    r.add_argument("--competitor", required=True, choices=["human", "ai"])
    r.add_argument("--round", required=True, choices=["build", "revision"])
    r.add_argument("--task", required=True)
    r.add_argument("--step", required=True)
    r.add_argument("--turns", type=int, required=True)
    r.add_argument("--seconds", type=float, required=True)
    r.add_argument("--ts-start", dest="ts_start", default="")
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_record)

    g = sub.add_parser("aggregate"); g.set_defaults(fn=cmd_aggregate)

    v = sub.add_parser("verify")
    v.add_argument("--bar", type=float, default=0.95, help="verified-correct composite bar")
    v.set_defaults(fn=cmd_verify)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
