#!/usr/bin/env python3
"""
grade_one.py — grade ONE candidate against a task's hidden ground truth.

This is the manual / interactive counterpart to the orchestrated loop. In the
grid, run_inner_loop.py grades candidates out-of-band; when you're driving Claude
Code interactively on your subscription, the agent grades its own candidate by
calling this after each attempt. No API key, no orchestrator, no claude -p.

Usage:
    python grade_one.py --task sample_bracket --candidate candidate.py
    python grade_one.py --task sample_bracket --candidate candidate.py --track spec

Reads the candidate (which must define a module-level `result` solid), builds it
in a sandbox, grades it on the six-layer composite, writes renders + feedback.md
under runs/manual/, and prints the feedback report. Never reads ground truth into
the agent's view — it just scores against it.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from run_inner_loop import load_task, load_ground_truth        # noqa: E402
from harness import run_candidate, score, render_compare, build_report, RewardConfig  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--candidate", required=True,
                    help="path to a .py file defining `result`")
    ap.add_argument("--track", default=None, choices=[None, "spec", "drawing"])
    ap.add_argument("--build-timeout", type=int, default=120)
    args = ap.parse_args()

    task = load_task(args.task)
    gt_mesh, gt_sig, gt_hist = load_ground_truth(task)

    code = Path(args.candidate).read_text()
    # Grade in a dedicated workspace so we never clobber the source candidate
    # (run_candidate writes its own candidate.py + export epilogue into the ws).
    ws = REPO / "runs" / "manual"
    ws.mkdir(parents=True, exist_ok=True)

    run = run_candidate(code, ws, timeout=args.build_timeout)
    if run.ok:
        rw = score(run.mesh, gt_mesh, candidate_sig=run.topology,
                   gt_sig=gt_sig, candidate_hist=run.histogram, gt_hist=gt_hist,
                   cfg=RewardConfig())
        renders = render_compare(run.mesh, gt_mesh, ws / "renders", tag="cand")
    else:
        rw = score(None, gt_mesh, gt_sig=gt_sig, gt_hist=gt_hist, cfg=RewardConfig())
        renders = []

    report = build_report(run, rw, renders)
    (ws / "feedback.md").write_text(report["markdown"])

    # Persist the candidate per-task so the leaderboard is reproducible from disk.
    # Gated on IMPROVEMENT (tracked in tasks/<task>/.best_score) so best_candidate.py
    # always holds the genuine best — a bbox-placeholder probe won't overwrite a solved
    # reconstruction. Lives under tasks/ (committable alongside the spec); mirrors
    # run_inner_loop.py's runs/<task>/best/ convention for the manual grade path.
    if run.ok:
        task_dir = REPO / "tasks" / args.task
        task_best = task_dir / "best_candidate.py"
        score_file = task_dir / ".best_score"
        src = Path(args.candidate).resolve()
        prev = None
        try:
            prev = float(score_file.read_text().strip()) if score_file.exists() else None
        except Exception:
            prev = None
        if src == task_best.resolve():
            # Grading the canonical best itself — (re)seed the score baseline so a
            # later worse attempt can't clobber it.
            if prev is None or rw.composite > prev:
                score_file.write_text(f"{rw.composite:.4f}")
            print(f"[best_candidate already at {task_best} ({rw.composite:.3f})]")
        elif prev is None or rw.composite >= prev:
            shutil.copy2(src, task_best)
            score_file.write_text(f"{rw.composite:.4f}")
            print(f"[best_candidate persisted ({rw.composite:.3f}) -> {task_best}]")
        else:
            print(f"[kept existing best {prev:.3f} (this attempt {rw.composite:.3f})]")

    print(report["markdown"])
    print(f"\n[renders + feedback.md written to {ws}]")
    if run.ok and run.step_path:
        print(f"[candidate STEP: {run.step_path}]")


if __name__ == "__main__":
    main()
