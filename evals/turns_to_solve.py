"""
turns_to_solve.py — the autonomy yardstick (design Rung 0).

The composite reward answers "how good is THIS attempt." It does NOT answer the
question the skill-decomposition design actually cares about: *can the loop rebuild
a fresh part start-to-finish on its own, and how many turns does it take?* That is
the honest benchmark for "did decomposition / a smarter prompt help" — turns-to-solve
on a LOCKED held-out part, not a score-delta on a part we already know is hard (which
is just tuning on the answer). See `build-specs/DESIGN_skill_decomposition.md` §5 (the
ladder, Rung 0) and §7 (invariant 2: the real metric is autonomy).

DESIGN — pure, offline, additive:
  * This is a READER over the experiment ledger (`loop/ledger.py`'s jsonl). It does NOT
    edit the ledger, the grader, or anything under `harness/` — it only reads rows that
    were already written. No model call, no network, no `ground_truth/` read.
  * "Solved" = composite `score >= bar` (default 0.95, the project's "solved" line).
  * turns-to-solve = the EARLIEST attempt number that crossed the bar, computed PER
    (task, worker) run and then reduced per task. A single ledger.jsonl can concatenate
    several runs (attempt counters reset to 1 each run — verified against the real
    `runs/sample_bracket/ledger.jsonl`), so we group by (task_id, worker) and take the
    min crossing attempt across groups; this is robust to concatenation.

ROBUSTNESS (the review's "crash on the common case" finding, design §8.6):
  * Early attempts fail a lot. A body-gate failure row carries a FULL `breakdown` (all
    layer keys) but a SPARSE `breakdown.raw` (`{"candidate_watertight": False}` only) and
    `score == 0.0`. This reader only needs the top-level `score`, which is always present,
    so it is robust by construction — but every field access is still defensive (`.get`),
    and malformed/blank lines are skipped, never fatal.

WHAT IT REPORTS (per task, then a summary):
  * first_solved_attempt — earliest attempt over the bar (None if never crossed)
  * best_score, n_attempts, solved (bool)
  * summary: n_tasks, n_solved, solve_rate, and the MEDIAN turns-to-solve over the
    solved tasks (the headline — "typical turns to solve a part it can solve").

CLI:
    python evals/turns_to_solve.py --run-dir runs/<session> [--bar 0.95] [--holdout] [--json]
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The project's "solved" line: composite >= this is a clean reconstruction.
DEFAULT_BAR = 0.95

_REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
#  Ledger reading
# --------------------------------------------------------------------------- #
def read_ledger_rows(path: str | Path) -> list[dict]:
    """Read every well-formed JSON row from one ledger.jsonl. Blank and malformed
    lines are skipped (never fatal) — a half-written final line on a killed run must
    not crash the scorer."""
    p = Path(path)
    rows: list[dict] = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def find_ledgers(run_dir: str | Path) -> list[Path]:
    """All ledger.jsonl files under a run dir (one per worker, recursively)."""
    rd = Path(run_dir)
    return sorted(rd.rglob("ledger.jsonl"))


def _row_score(rec: dict) -> float:
    """Top-level composite score for a row. Always present in a real row; defended
    anyway (returns -1.0 if absent/non-numeric so it can never be 'solved')."""
    s = rec.get("score")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s)
    return -1.0


def _row_attempt(rec: dict) -> int | None:
    a = rec.get("attempt")
    if isinstance(a, int) and not isinstance(a, bool):
        return a
    return None


# --------------------------------------------------------------------------- #
#  Per-task turns-to-solve
# --------------------------------------------------------------------------- #
@dataclass
class TaskResult:
    task_id: str
    solved: bool
    first_solved_attempt: int | None   # earliest attempt over the bar (per-run min)
    best_score: float
    n_attempts: int                    # total rows seen for this task
    n_runs: int                        # distinct (worker) groups
    bar: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "solved": self.solved,
            "first_solved_attempt": self.first_solved_attempt,
            "best_score": round(self.best_score, 4),
            "n_attempts": self.n_attempts,
            "n_runs": self.n_runs,
            "bar": self.bar,
        }


def score_rows(rows: list[dict], *, bar: float = DEFAULT_BAR) -> dict[str, TaskResult]:
    """Reduce a flat list of ledger rows (possibly across many tasks/workers/runs) to
    one TaskResult per task.

    turns-to-solve is computed PER (task, worker) group so concatenated runs (attempt
    counters reset to 1) don't corrupt the 'earliest crossing' — then the per-task value
    is the MIN earliest-crossing across its groups (the best run is the honest 'can it
    solve this, and how fast at best'). best_score and n_attempts aggregate across all
    rows for the task.
    """
    # group[(task, worker)] -> list of (attempt, score)
    groups: dict[tuple[str, str], list[tuple[int | None, float]]] = {}
    per_task_scores: dict[str, list[float]] = {}
    for rec in rows:
        tid = rec.get("task_id")
        if not isinstance(tid, str):
            continue
        worker = rec.get("worker")
        worker = worker if isinstance(worker, str) else "_"
        sc = _row_score(rec)
        at = _row_attempt(rec)
        groups.setdefault((tid, worker), []).append((at, sc))
        per_task_scores.setdefault(tid, []).append(sc)

    # collect per-task: distinct workers, earliest crossing attempt across groups
    task_workers: dict[str, set[str]] = {}
    task_first_solved: dict[str, int | None] = {}
    for (tid, worker), pairs in groups.items():
        task_workers.setdefault(tid, set()).add(worker)
        # earliest attempt in THIS group whose score crossed the bar
        crossing = [at for (at, sc) in pairs if sc >= bar and at is not None]
        group_first = min(crossing) if crossing else None
        if group_first is not None:
            prev = task_first_solved.get(tid)
            task_first_solved[tid] = group_first if prev is None else min(prev, group_first)
        else:
            task_first_solved.setdefault(tid, None)

    results: dict[str, TaskResult] = {}
    for tid, scores in per_task_scores.items():
        first = task_first_solved.get(tid)
        results[tid] = TaskResult(
            task_id=tid,
            solved=first is not None,
            first_solved_attempt=first,
            best_score=max(scores) if scores else -1.0,
            n_attempts=len(scores),
            n_runs=len(task_workers.get(tid, set())),
            bar=bar,
        )
    return results


# --------------------------------------------------------------------------- #
#  Held-out filtering (reads the manifest `holdout` field)
# --------------------------------------------------------------------------- #
def holdout_task_ids(manifest_path: str | Path | None = None) -> set[str]:
    """Task ids flagged `holdout: true` in tasks/manifest.yaml. Empty set if the
    manifest or pyyaml is unavailable (the scorer still works un-filtered)."""
    mp = Path(manifest_path) if manifest_path else (_REPO / "tasks" / "manifest.yaml")
    if not mp.exists():
        return set()
    try:
        import yaml
        data = yaml.safe_load(mp.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out: set[str] = set()
    for t in (data or {}).get("tasks", []) or []:
        if isinstance(t, dict) and t.get("holdout") and isinstance(t.get("id"), str):
            out.add(t["id"])
    return out


# --------------------------------------------------------------------------- #
#  Summary
# --------------------------------------------------------------------------- #
@dataclass
class Summary:
    bar: float
    n_tasks: int
    n_solved: int
    solve_rate: float
    median_turns_to_solve: float | None   # median first_solved_attempt over solved tasks
    tasks: list[TaskResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bar": self.bar,
            "n_tasks": self.n_tasks,
            "n_solved": self.n_solved,
            "solve_rate": round(self.solve_rate, 4),
            "median_turns_to_solve": self.median_turns_to_solve,
            "tasks": [t.as_dict() for t in sorted(self.tasks, key=lambda r: r.task_id)],
        }


def summarize(results: dict[str, TaskResult], *, bar: float = DEFAULT_BAR) -> Summary:
    tasks = list(results.values())
    solved = [t for t in tasks if t.solved]
    solved_turns = [t.first_solved_attempt for t in solved if t.first_solved_attempt is not None]
    median = float(statistics.median(solved_turns)) if solved_turns else None
    n = len(tasks)
    return Summary(
        bar=bar,
        n_tasks=n,
        n_solved=len(solved),
        solve_rate=(len(solved) / n) if n else 0.0,
        median_turns_to_solve=median,
        tasks=tasks,
    )


def score_run_dir(run_dir: str | Path, *, bar: float = DEFAULT_BAR,
                  holdout_only: bool = False,
                  manifest_path: str | Path | None = None) -> Summary:
    """End-to-end: read every ledger under run_dir, score, optionally restrict to the
    held-out set, and summarize."""
    rows: list[dict] = []
    for led in find_ledgers(run_dir):
        rows.extend(read_ledger_rows(led))
    if holdout_only:
        ho = holdout_task_ids(manifest_path)
        rows = [r for r in rows if r.get("task_id") in ho]
    results = score_rows(rows, bar=bar)
    return summarize(results, bar=bar)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def _render(summary: Summary) -> str:
    lines = [
        f"TURNS-TO-SOLVE  (bar={summary.bar:g})",
        f"  tasks={summary.n_tasks}  solved={summary.n_solved}  "
        f"solve_rate={summary.solve_rate:.2f}  "
        f"median_turns_to_solve={summary.median_turns_to_solve}",
        "",
        f"  {'task':<22}{'solved':<8}{'turns':<7}{'best':<8}{'attempts':<9}runs",
    ]
    for t in sorted(summary.tasks, key=lambda r: r.task_id):
        turns = "-" if t.first_solved_attempt is None else str(t.first_solved_attempt)
        lines.append(
            f"  {t.task_id:<22}{('yes' if t.solved else 'no'):<8}{turns:<7}"
            f"{t.best_score:<8.3f}{t.n_attempts:<9}{t.n_runs}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="turns-to-solve scorer over the experiment ledger")
    ap.add_argument("--run-dir", required=True, help="run dir to scan for ledger.jsonl (recursive)")
    ap.add_argument("--bar", type=float, default=DEFAULT_BAR, help="composite score that counts as solved")
    ap.add_argument("--holdout", action="store_true", help="restrict to tasks flagged holdout:true in the manifest")
    ap.add_argument("--manifest", default=None, help="path to tasks/manifest.yaml (default: repo manifest)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    summary = score_run_dir(args.run_dir, bar=args.bar,
                            holdout_only=args.holdout, manifest_path=args.manifest)
    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
    else:
        print(_render(summary))


if __name__ == "__main__":
    main()
