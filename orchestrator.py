#!/usr/bin/env python3
"""
orchestrator.py — spawn and manage the worker grid.

This is the top of the agent hierarchy:

    orchestrator  (this file)
      └── worker × N per task           run_inner_loop.py, one isolated workspace each
            └── subagents (per turn)     vision / debugger, spawned by the worker via Task

It launches `workers` copies of run_inner_loop.py per task. **Each worker gets its
own run directory** (runs/<session>/<task>/<worker>/) — separate ledger, separate
candidate workspaces, separate best/. That isolation is deliberate and load-
bearing: concurrent CAD-eval agents sharing a directory WILL clobber each other's
files (learned the hard way). The orchestrator aggregates a global best across
workers afterwards.

Backends:
  * tmux        — one window per worker in a detached session you can attach to.
  * subprocess  — background processes with per-worker log files; works anywhere,
                  including Windows (where tmux usually means WSL).

Usage:
    python orchestrator.py                      # use config.yaml
    python orchestrator.py --workers 8 --tasks sample_bracket --proposer claude
    python orchestrator.py --dry-run            # print the commands, launch nothing
    python orchestrator.py --aggregate-only     # just rebuild the global leaderboard
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from loop.answer_key_guard import restore_orphaned
from loop.billing import print_billing_banner, scrub_billing_env

REPO = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def worker_cmd(task: str, worker: str, run_dir: Path, w: dict) -> list[str]:
    """The exact command one worker runs."""
    cmd = [sys.executable, str(REPO / "run_inner_loop.py"),
           "--task", task, "--worker", worker, "--run-dir", str(run_dir),
           "--proposer", str(w["proposer"]), "--model", str(w["model"]),
           "--budget", str(w["budget"]), "--target", str(w["target"]),
           "--build-timeout", str(w["build_timeout"]),
           "--min-delta", str(w["min_delta"])]
    if w.get("track"):
        cmd += ["--track", str(w["track"])]
    return cmd


def launch_tmux(session: str, jobs: list[dict], dry: bool) -> None:
    if not dry:
        if not shutil.which("tmux"):
            raise SystemExit("tmux not found. Use --backend subprocess instead.")
        # fresh session
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "control"],
                       check=True)
    for j in jobs:
        win = f"{j['task']}-{j['worker']}"
        line = " ".join(_shquote(c) for c in j["cmd"])
        if dry:
            print(f"[tmux {session}:{win}] {line}")
            continue
        subprocess.run(["tmux", "new-window", "-t", session, "-n", win], check=True)
        subprocess.run(["tmux", "send-keys", "-t", f"{session}:{win}",
                        f"cd {_shquote(str(REPO))} && {line}", "C-m"], check=True)
    if not dry:
        print(f"launched {len(jobs)} workers in tmux session '{session}'.")
        print(f"attach with:  tmux attach -t {session}")
        print(f"watch with :  python watcher.py --session {session}")


def launch_subprocess(session: str, jobs: list[dict], dry: bool) -> None:
    log_dir = REPO / "runs" / session / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for j in jobs:
        line = " ".join(_shquote(c) for c in j["cmd"])
        log = log_dir / f"{j['task']}-{j['worker']}.log"
        if dry:
            print(f"[bg > {log.name}] {line}")
            continue
        f = open(log, "w")
        p = subprocess.Popen(j["cmd"], cwd=str(REPO), stdout=f, stderr=subprocess.STDOUT)
        procs.append({"task": j["task"], "worker": j["worker"],
                      "pid": p.pid, "log": str(log)})
        print(f"[pid {p.pid}] {j['task']}/{j['worker']}  -> {log}")
    if not dry:
        (REPO / "runs" / session / "pids.json").write_text(json.dumps(procs, indent=2))
        print(f"launched {len(procs)} workers as background processes.")
        print(f"watch with :  python watcher.py --session {session}")


def aggregate(session: str) -> dict:
    """Scan every worker ledger, build a global per-task leaderboard, and copy
    the global-best STEP for each task to runs/<session>/<task>/BEST/."""
    base = REPO / "runs" / session
    best: dict[str, dict] = {}
    for ledger in base.glob("*/*/ledger.jsonl"):
        for line in ledger.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t, s = rec.get("task_id"), rec.get("score", 0.0)
            if t and (t not in best or s > best[t]["score"]):
                best[t] = {"score": s, "worker": rec.get("worker"),
                           "attempt": rec.get("attempt"),
                           "dir": str(ledger.parent)}
    for t, info in best.items():
        src = Path(info["dir"]) / "best" / "result.step"
        if src.exists():
            dst = base / t / "BEST"
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst / "result.step")
            shutil.copy(Path(info["dir"]) / "best" / "candidate.py",
                        dst / "candidate.py")
            info["promoted_to"] = str(dst)
    (base / "leaderboard.json").write_text(json.dumps(best, indent=2))
    return best


def _shquote(s: str) -> str:
    return s if all(c.isalnum() or c in "-_=/.:" for c in s) else "'" + s.replace("'", "'\\''") + "'"


def main():
    cfg = load_config(REPO / "config.yaml")
    g, w = cfg.get("grid", {}), cfg.get("worker", {})

    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=cfg.get("session", "cadar"))
    ap.add_argument("--backend", default=g.get("backend", "subprocess"),
                    choices=["tmux", "subprocess"])
    ap.add_argument("--workers", type=int, default=g.get("workers", 4))
    ap.add_argument("--tasks", nargs="*", default=g.get("tasks", ["sample_bracket"]))
    ap.add_argument("--proposer", default=w.get("proposer", "claude"))
    ap.add_argument("--model", default=w.get("model", "opus"))
    ap.add_argument("--budget", type=int, default=w.get("budget", 30))
    ap.add_argument("--target", type=float, default=w.get("target", 0.95))
    ap.add_argument("--build-timeout", type=int, default=w.get("build_timeout", 120))
    ap.add_argument("--track", default=w.get("track"))
    ap.add_argument("--min-delta", type=float, default=w.get("min_delta", 0.0))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    if args.aggregate_only:
        best = aggregate(args.session)
        print(json.dumps(best, indent=2))
        return

    wcfg = {"proposer": args.proposer, "model": args.model, "budget": args.budget,
            "target": args.target, "build_timeout": args.build_timeout,
            "track": args.track, "min_delta": args.min_delta}

    jobs = []
    for task in args.tasks:
        for i in range(args.workers):
            worker = f"w{i}"
            run_dir = REPO / "runs" / args.session / task / worker
            jobs.append({"task": task, "worker": worker,
                         "cmd": worker_cmd(task, worker, run_dir, wcfg)})

    # session manifest (used by watcher.py)
    manifest = {"session": args.session, "backend": args.backend,
                "created": time.time(), "jobs":
                [{"task": j["task"], "worker": j["worker"]} for j in jobs],
                "worker_cfg": wcfg, "tasks": args.tasks}
    if not args.dry_run:
        (REPO / "runs" / args.session).mkdir(parents=True, exist_ok=True)
        (REPO / "runs" / args.session / "session.json").write_text(
            json.dumps(manifest, indent=2))

    print(f"== orchestrator: {len(jobs)} workers "
          f"({args.workers}/task x {len(args.tasks)} tasks) backend={args.backend} ==")
    # Defense in depth: strip billing-steering vars from THIS process env before spawning
    # workers, so workers (and the candidate sandbox they inherit) can't pass a metered
    # credential to `claude -p`. The per-spawn scrub in policies.py is the backstop.
    scrub_billing_env()
    print_billing_banner()   # once per launch — which plane (subscription) is active
    # Self-heal the answer-key guard: if a previous run was hard-killed mid-turn, its
    # hidden dimension/score keys may be stranded out-of-repo. Put any back before launch.
    _orphans = restore_orphaned(REPO)
    if _orphans:
        print(f"[guard] restored {len(_orphans)} answer-key(s) stranded by a prior kill")
    if args.backend == "tmux":
        launch_tmux(args.session, jobs, args.dry_run)
    else:
        launch_subprocess(args.session, jobs, args.dry_run)


if __name__ == "__main__":
    main()
