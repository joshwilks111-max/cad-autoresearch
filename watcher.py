#!/usr/bin/env python3
"""
watcher.py — keep the grid looping and watch it work.

Karpathy runs tmux grids of agents with a watcher script that keeps them looping.
This is that script. It reads the session manifest written by orchestrator.py and:

  * prints a live per-task leaderboard from the aggregated ledgers,
  * detects dead workers and (subprocess backend) restarts them until the global
    wall-clock budget is hit or every task reaches target,
  * optionally runs an EXPERIMENTAL meta agent (the bilevel outer loop) that reads
    the aggregate ledger and may edit program.md to unstick a plateaued grid.

Usage:
    python watcher.py --session cadar
    python watcher.py --session cadar --meta-agent      # enable the outer loop
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent
import orchestrator as orch   # reuse worker_cmd / aggregate  # noqa: E402
from loop.billing import print_billing_banner, subscription_env  # keep on the subscription  # noqa: E402


def read_manifest(session: str) -> dict:
    p = REPO / "runs" / session / "session.json"
    if not p.exists():
        raise SystemExit(f"no session manifest at {p}. Launch orchestrator.py first.")
    return json.loads(p.read_text())


def pid_alive(pid: int) -> bool:
    try:
        import os
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def leaderboard(session: str) -> dict:
    best = orch.aggregate(session)   # also promotes global-best STEPs
    return best


def run_meta_agent(session: str, model: str, cli: str = "claude",
                   timeout: int = 600) -> None:
    """Outer loop: hand the aggregate ledger summary to a Claude Code agent and
    let it edit program.md per prompts/meta_agent.md. Best-effort; never fatal."""
    summary = (REPO / "runs" / session / "leaderboard.json")
    prompt = (
        "Read ./prompts/meta_agent.md and follow it. You are the OUTER loop of a "
        "CAD autoresearch grid. Inspect the aggregate results at "
        f"{summary} and a sample of worker ledgers under runs/{session}/. "
        "If the grid is plateaued in a way that a prompt change could fix, make a "
        "SMALL, surgical edit to ./program.md (the worker instructions). Do not "
        "touch the harness or any ground_truth/. Explain your edit in one line, "
        "then print META_DONE."
    )
    cmd = [cli, "-p", prompt, "--model", model,
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Read,Edit,Glob,Grep"]
    try:
        # env scrub: the meta-agent spawns `claude` too — keep it on the subscription.
        subprocess.run(cmd, cwd=str(REPO), timeout=timeout, capture_output=True,
                       env=subscription_env())
    except Exception as e:
        print(f"[watcher] meta agent skipped: {e!r}")


def main():
    cfg = yaml.safe_load((REPO / "config.yaml").read_text()) if (REPO / "config.yaml").exists() else {}
    wc = cfg.get("watcher", {})

    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=cfg.get("session", "cadar"))
    ap.add_argument("--poll-seconds", type=int, default=wc.get("poll_seconds", 20))
    ap.add_argument("--wall-clock-minutes", type=int,
                    default=wc.get("wall_clock_minutes", 480))
    ap.add_argument("--restart-dead", action="store_true",
                    default=wc.get("restart_dead", True))
    ap.add_argument("--meta-agent", action="store_true",
                    default=wc.get("meta_agent", False))
    ap.add_argument("--meta-every-minutes", type=int,
                    default=wc.get("meta_every_minutes", 30))
    args = ap.parse_args()

    man = read_manifest(args.session)
    target = float(man["worker_cfg"]["target"])
    t_start = time.time()
    last_meta = 0.0
    pids_path = REPO / "runs" / args.session / "pids.json"

    print(f"[watcher] session={args.session} backend={man['backend']} "
          f"target={target} wall_clock={args.wall_clock_minutes}min")
    print_billing_banner()   # which plane (subscription) the meta-agent will use

    while True:
        elapsed_min = (time.time() - t_start) / 60.0
        board = leaderboard(args.session)
        line = "  ".join(f"{t}={info['score']:.3f}" for t, info in board.items()) or "(no results yet)"
        print(f"[watcher t+{elapsed_min:5.1f}m] {line}")

        all_done = board and all(info["score"] >= target for info in board.values()) \
            and len(board) >= len(man["tasks"])
        if all_done:
            print("[watcher] all tasks reached target. stopping.")
            break
        if elapsed_min >= args.wall_clock_minutes:
            print("[watcher] wall-clock budget reached. stopping.")
            break

        # restart dead workers (subprocess backend only)
        if args.restart_dead and man["backend"] == "subprocess" and pids_path.exists():
            procs = json.loads(pids_path.read_text())
            for rec in procs:
                if not pid_alive(rec["pid"]):
                    task, worker = rec["task"], rec["worker"]
                    # only restart if that task hasn't hit target
                    if board.get(task, {}).get("score", -1) >= target:
                        continue
                    run_dir = REPO / "runs" / args.session / task / worker
                    cmd = orch.worker_cmd(task, worker, run_dir, man["worker_cfg"])
                    f = open(rec["log"], "a")
                    p = subprocess.Popen(cmd, cwd=str(REPO), stdout=f,
                                         stderr=subprocess.STDOUT)
                    rec["pid"] = p.pid
                    print(f"[watcher] restarted {task}/{worker} -> pid {p.pid}")
            pids_path.write_text(json.dumps(procs, indent=2))

        # optional outer loop
        if args.meta_agent and (time.time() - last_meta) / 60.0 >= args.meta_every_minutes:
            print("[watcher] invoking meta agent (outer loop)...")
            run_meta_agent(args.session, man["worker_cfg"]["model"])
            last_meta = time.time()

        time.sleep(args.poll_seconds)

    print(json.dumps(leaderboard(args.session), indent=2))


if __name__ == "__main__":
    main()
