#!/usr/bin/env python3
"""
run_inner_loop.py — one worker grinding one task.

The Karpathy inner loop, made concrete for CAD:

    repeat until budget exhausted or target hit:
        candidate = proposer.propose(task, history)   # mock or Claude Code
        run       = harness.run_candidate(candidate)  # sandboxed build + export
        reward    = harness.score(run.mesh, gt.mesh)   # six-layer composite
        renders   = harness.render_compare(...)        # multimodal feedback
        report    = harness.build_report(...)          # terse "what to fix"
        kept      = ledger.consider(score)             # keep/discard rule
        ledger.log(...)                                # lab notebook

The worker is deliberately dumb: all intelligence lives in the proposer (the
agent) and all truth lives in the reward. Run many of these in parallel via
orchestrator.py.

Offline smoke test:
    python run_inner_loop.py --task sample_bracket --proposer mock --budget 6

Real agent:
    python run_inner_loop.py --task sample_bracket --proposer claude \\
        --model opus --budget 30 --target 0.95
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import trimesh
import yaml

from harness import run_candidate, score, RewardConfig, render_compare, build_report
from loop import Ledger, make_proposer

REPO = Path(__file__).resolve().parent


def load_task(task_id: str) -> dict:
    manifest = yaml.safe_load((REPO / "tasks" / "manifest.yaml").read_text())
    for t in manifest["tasks"]:
        if t["id"] == task_id:
            t["_dir"] = REPO / "tasks" / task_id
            return t
    raise SystemExit(f"task '{task_id}' not in tasks/manifest.yaml")


# GT surface-histogram cache for the hybrid Layer-4. Keyed by the GT STEP's
# (path, size, mtime) — NOT the bare task_id — so a regenerated ground truth
# invalidates the cache instead of serving a stale histogram (the content-hash
# lesson). Lazy: computed once per GT, reused across every grade in a grid run so
# the orchestrator doesn't re-import the same ~10 GT STEPs thousands of times.
_GT_HIST_CACHE: dict[tuple, dict | None] = {}


def _gt_histogram(gt_step: Path) -> dict | None:
    """Surface-type histogram of a GT STEP, signed from the RE-IMPORTED solid
    (the seam-merge lesson: the histogram must come from the same representation
    the grader compares against). Cached by (path, size, mtime_ns). Returns None if
    the STEP is missing or the tool/import is unavailable — the grader then falls
    back to exact-count topology, so a missing histogram degrades gracefully.

    Cache discipline (review-hardened): the key uses st_mtime_ns (nanosecond, not
    int-second) so a GT regenerated within the same wall-clock second cannot serve a
    stale histogram. A SUCCESSFUL result is cached; a FAILED one (None) is NOT cached,
    so a transient import/OCP hiccup on one grade doesn't permanently downgrade the
    hybrid layer to exact-only for the rest of a long grid run (the silent-corruption
    path two adversarial reviewers flagged)."""
    if not gt_step.exists():
        return None
    try:
        st = gt_step.stat()
        key = (str(gt_step), st.st_size, st.st_mtime_ns)
    except OSError:
        key = None                  # can't form a stable key -> don't cache, just compute
    if key is not None and key in _GT_HIST_CACHE:
        return _GT_HIST_CACHE[key]
    hist = None
    try:
        from surface_histogram import surface_histogram, from_step
        hist = surface_histogram(from_step(str(gt_step)))
    except Exception:
        hist = None
    # Cache only successes. A transient failure must be retried next grade, not
    # permanently pinned to None for the process lifetime.
    if key is not None and hist is not None:
        _GT_HIST_CACHE[key] = hist
    return hist


def load_ground_truth(task: dict):
    gt_dir = task["_dir"] / "ground_truth"
    stl = gt_dir / "result.stl"
    if not stl.exists():
        raise SystemExit(
            f"ground truth not built for '{task['id']}'. Run:\n"
            f"    python tasks/{task['id']}/make_ground_truth.py")
    mesh = trimesh.load(str(stl), force="mesh")
    sig = None
    if (gt_dir / "topology.json").exists():
        try:
            sig = json.loads((gt_dir / "topology.json").read_text())
        except Exception:
            sig = None
    gt_hist = _gt_histogram(gt_dir / "result.step")
    return mesh, sig, gt_hist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--proposer", default="mock", choices=["mock", "claude"])
    ap.add_argument("--model", default="opus")
    ap.add_argument("--budget", type=int, default=8, help="max attempts (turns)")
    ap.add_argument("--target", type=float, default=0.97, help="stop if composite >= target")
    ap.add_argument("--worker", default="w0", help="worker id (for the ledger)")
    ap.add_argument("--run-dir", default=None, help="where to write attempts/ledger")
    ap.add_argument("--build-timeout", type=int, default=120)
    ap.add_argument("--min-delta", type=float, default=0.0)
    ap.add_argument("--track", default=None, choices=[None, "spec", "drawing"],
                    help="override which input track to use")
    args = ap.parse_args()

    task = load_task(args.task)
    gt_mesh, gt_sig, gt_hist = load_ground_truth(task)

    run_dir = Path(args.run_dir) if args.run_dir else REPO / "runs" / args.task
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")

    track = args.track or task.get("default_track", "spec")
    spec_path = task["_dir"] / task["spec"]
    drawing_path = (task["_dir"] / task["drawing"]) if task.get("drawing") else None

    proposer_kwargs = {}
    if args.proposer == "claude":
        proposer_kwargs = dict(repo_dir=REPO, model=args.model)
    proposer = make_proposer(args.proposer, **proposer_kwargs)

    cfg = RewardConfig()
    history: list[dict] = []
    print(f"[{args.worker}] task={args.task} track={track} proposer={args.proposer} "
          f"budget={args.budget} target={args.target} (resume best={ledger.best(args.task):.3f})")

    for attempt in range(1, args.budget + 1):
        ws = run_dir / f"{args.worker}" / f"attempt_{attempt:03d}"
        task_view = {
            "task_id": args.task,
            "workspace": str(ws),
            "spec_path": str(spec_path) if track == "spec" else "",
            "drawing_path": str(drawing_path) if (track == "drawing" and drawing_path) else "",
            "best": ledger.best(args.task),
        }
        t0 = time.time()
        cand = proposer.propose(task_view, history)
        if not cand.code.strip():
            print(f"[{args.worker}] attempt {attempt}: proposer produced no code "
                  f"({cand.meta}); skipping")
            history.append({"feedback_markdown": f"Proposer failed: {cand.meta}. Retry."})
            continue

        run = run_candidate(cand.code, ws, timeout=args.build_timeout)
        if run.ok:
            rw = score(run.mesh, gt_mesh, candidate_sig=run.topology, gt_sig=gt_sig,
                       candidate_hist=run.histogram, gt_hist=gt_hist, cfg=cfg)
            renders = render_compare(run.mesh, gt_mesh, ws / "renders", tag="cand")
        else:
            rw = score(None, gt_mesh, gt_sig=gt_sig, gt_hist=gt_hist, cfg=cfg)   # body gate -> 0
            renders = []
        report = build_report(run, rw, renders, attempt=attempt)

        kept = ledger.consider(args.task, rw.composite, min_delta=args.min_delta)
        ledger.log(task_id=args.task, worker=args.worker, attempt=attempt,
                   code=cand.code, score=rw.composite, breakdown=rw.to_dict(),
                   kept=kept, seconds=time.time() - t0,
                   error=None if run.ok else run.error,
                   extra={"track": track, "proposer": proposer.name, **cand.meta})

        (ws / "feedback.md").write_text(report["markdown"])
        if kept and run.step_path:
            best_dir = run_dir / "best"
            best_dir.mkdir(exist_ok=True)
            (best_dir / "result.step").write_bytes(Path(run.step_path).read_bytes())
            (best_dir / "candidate.py").write_text(cand.code)

        flag = "KEPT " if kept else "disc."
        print(f"[{args.worker}] attempt {attempt:03d} {flag} {rw.summary()}")
        history.append({"attempt": attempt, "score": rw.composite,
                        "feedback_markdown": report["markdown"], "kept": kept})

        if rw.composite >= args.target:
            print(f"[{args.worker}] TARGET HIT ({rw.composite:.3f} >= {args.target}) "
                  f"in {attempt} attempts")
            break

    print(f"[{args.worker}] done. best={ledger.best(args.task):.3f}  ledger={ledger.path}")


if __name__ == "__main__":
    main()
