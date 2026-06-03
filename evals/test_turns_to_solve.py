"""
test_turns_to_solve.py — pytest for the turns-to-solve scorer (design Rung 0).

HERMETIC. Every test synthesizes its OWN ledger.jsonl in pytest's tmp_path — it does
NOT read `runs/` (which is gitignored, so depending on it would pass here and fail in
CI / a fresh clone). The synthesized rows mirror the REAL ledger shapes verified against
`runs/sample_bracket/ledger.jsonl` (a body-gate failure row carries a full `breakdown`
but a sparse `breakdown.raw = {"candidate_watertight": False}` and `score == 0.0`; a
single file can concatenate runs whose `attempt` counters reset to 1).

Asserts:
  * first-over-bar attempt is correct (and is the EARLIEST crossing, per run);
  * None / not-solved when the bar is never crossed;
  * body-gate failure rows (sparse raw, score 0.0, error set) don't crash and read as
    not-solved;
  * concatenated runs (attempt reset) + multi-worker are grouped correctly;
  * malformed / blank lines are skipped, never fatal;
  * holdout filtering reads the manifest `holdout` field;
  * the summary's median turns-to-solve is over SOLVED tasks only.
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

from turns_to_solve import (  # noqa: E402
    DEFAULT_BAR,
    _render,
    find_ledgers,
    holdout_task_ids,
    read_ledger_rows,
    score_rows,
    score_run_dir,
    summarize,
)


# --------------------------------------------------------------------------- #
#  Row builders — mirror the real ledger schema (loop/ledger.py:55-70)
# --------------------------------------------------------------------------- #
def _ok_row(task_id: str, worker: str, attempt: int, score: float) -> dict:
    """A normal graded row: full breakdown with all layer keys + a populated raw."""
    return {
        "ts": 1780000000.0 + attempt,
        "task_id": task_id,
        "worker": worker,
        "attempt": attempt,
        "code_hash": "deadbeef0000",
        "code_len": 500,
        "score": round(score, 4),
        "breakdown": {
            "composite": round(score, 4), "body": 1.0, "volume": 0.9, "bbox": 1.0,
            "topology": 0.8, "iou": score, "chamfer": 0.95, "siou": 0.9,
            "raw": {"volume_candidate": 1.0, "volume_gt": 1.0, "iou": score},
        },
        "kept": True,
        "seconds": 12.0,
        "error": None,
        "track": "spec",
        "proposer": "claude",
    }


def _body_gate_row(task_id: str, worker: str, attempt: int) -> dict:
    """A build-failure row: score 0.0, error set, SPARSE breakdown.raw (the common
    early-attempt case the reader must not crash on)."""
    return {
        "ts": 1780000000.0 + attempt,
        "task_id": task_id,
        "worker": worker,
        "attempt": attempt,
        "code_hash": "0000badc0de0",
        "code_len": 120,
        "score": 0.0,
        "breakdown": {
            "composite": 0.0, "body": 0.0, "volume": 0.0, "bbox": 0.0,
            "topology": 0.0, "iou": 0.0, "chamfer": 0.0, "siou": 0.0,
            "raw": {"candidate_watertight": False},
        },
        "kept": False,
        "seconds": 3.0,
        "error": "candidate exited 2",
        "track": "spec",
        "proposer": "claude",
    }


def _write_ledger(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
#  first-over-bar correctness
# --------------------------------------------------------------------------- #
def test_first_solved_attempt_is_earliest_crossing():
    rows = [
        _ok_row("t", "w0", 1, 0.12),
        _ok_row("t", "w0", 2, 0.86),
        _ok_row("t", "w0", 3, 0.97),   # first crossing of 0.95
        _ok_row("t", "w0", 4, 0.99),
    ]
    res = score_rows(rows, bar=0.95)
    assert res["t"].solved is True
    assert res["t"].first_solved_attempt == 3
    assert res["t"].best_score == pytest.approx(0.99)
    assert res["t"].n_attempts == 4


def test_never_crossed_is_unsolved_with_none():
    rows = [_ok_row("t", "w0", 1, 0.40), _ok_row("t", "w0", 2, 0.88)]
    res = score_rows(rows, bar=0.95)
    assert res["t"].solved is False
    assert res["t"].first_solved_attempt is None
    assert res["t"].best_score == pytest.approx(0.88)


def test_bar_is_inclusive():
    rows = [_ok_row("t", "w0", 1, 0.95)]
    res = score_rows(rows, bar=0.95)
    assert res["t"].solved is True
    assert res["t"].first_solved_attempt == 1


# --------------------------------------------------------------------------- #
#  robustness: body-gate rows, malformed lines
# --------------------------------------------------------------------------- #
def test_body_gate_rows_do_not_crash_and_read_unsolved(tmp_path):
    led = _write_ledger(tmp_path / "w0" / "ledger.jsonl", [
        _body_gate_row("t", "w0", 1),
        _body_gate_row("t", "w0", 2),
    ])
    rows = read_ledger_rows(led)
    assert len(rows) == 2
    res = score_rows(rows, bar=0.95)
    assert res["t"].solved is False
    assert res["t"].first_solved_attempt is None
    assert res["t"].best_score == pytest.approx(0.0)


def test_body_gate_then_recovery_solves():
    rows = [
        _body_gate_row("t", "w0", 1),
        _ok_row("t", "w0", 2, 0.50),
        _ok_row("t", "w0", 3, 0.98),
    ]
    res = score_rows(rows, bar=0.95)
    assert res["t"].first_solved_attempt == 3


def test_malformed_and_blank_lines_are_skipped(tmp_path):
    p = tmp_path / "w0" / "ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps(_ok_row("t", "w0", 1, 0.97))
    # blank line, a truncated/half-written final line, and a non-object line
    p.write_text(good + "\n\n" + "{not valid json" + "\n" + "[1,2,3]\n", encoding="utf-8")
    rows = read_ledger_rows(p)
    assert len(rows) == 1          # only the good object row
    res = score_rows(rows, bar=0.95)
    assert res["t"].first_solved_attempt == 1


def test_missing_score_never_counts_as_solved():
    bad = _ok_row("t", "w0", 1, 0.99)
    del bad["score"]               # malformed row missing the score field
    res = score_rows([bad], bar=0.95)
    assert res["t"].solved is False
    assert res["t"].best_score == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
#  concatenation + multi-worker grouping
# --------------------------------------------------------------------------- #
def test_concatenated_runs_with_attempt_reset():
    # Two runs in one file: run A solves at its attempt 4; run B (counter reset)
    # solves at its attempt 2. The honest 'best run' turns-to-solve is min(4, 2) = 2.
    rows = [
        _ok_row("t", "w0", 1, 0.10), _ok_row("t", "w0", 2, 0.70),
        _ok_row("t", "w0", 3, 0.80), _ok_row("t", "w0", 4, 0.96),
        # second run, same worker label, attempt resets:
        _ok_row("t", "w0", 1, 0.20), _ok_row("t", "w0", 2, 0.99),
    ]
    res = score_rows(rows, bar=0.95)
    # NB: grouped by (task, worker); within the group the earliest crossing attempt is 2.
    assert res["t"].first_solved_attempt == 2
    assert res["t"].n_attempts == 6


def test_multi_worker_takes_best_run():
    rows = [
        _ok_row("t", "w0", 1, 0.50), _ok_row("t", "w0", 2, 0.60),  # w0 never solves
        _ok_row("t", "w1", 1, 0.50), _ok_row("t", "w1", 2, 0.97),  # w1 solves at 2
    ]
    res = score_rows(rows, bar=0.95)
    assert res["t"].solved is True
    assert res["t"].first_solved_attempt == 2
    assert res["t"].n_runs == 2


def test_multiple_tasks_separated():
    rows = [
        _ok_row("a", "w0", 1, 0.99),
        _ok_row("b", "w0", 1, 0.40), _ok_row("b", "w0", 2, 0.50),
    ]
    res = score_rows(rows, bar=0.95)
    assert res["a"].solved is True and res["a"].first_solved_attempt == 1
    assert res["b"].solved is False


# --------------------------------------------------------------------------- #
#  summary
# --------------------------------------------------------------------------- #
def test_summary_median_over_solved_only():
    rows = [
        _ok_row("a", "w0", 2, 0.99),   # solved at 2
        _ok_row("b", "w0", 4, 0.99),   # solved at 4
        _ok_row("c", "w0", 1, 0.10),   # unsolved -> excluded from median
    ]
    summary = summarize(score_rows(rows, bar=0.95), bar=0.95)
    assert summary.n_tasks == 3
    assert summary.n_solved == 2
    assert summary.solve_rate == pytest.approx(2 / 3)
    assert summary.median_turns_to_solve == pytest.approx(3.0)   # median(2, 4)


def test_summary_no_solved_has_none_median():
    rows = [_ok_row("a", "w0", 1, 0.10)]
    summary = summarize(score_rows(rows, bar=0.95), bar=0.95)
    assert summary.n_solved == 0
    assert summary.median_turns_to_solve is None


# --------------------------------------------------------------------------- #
#  end-to-end over a run dir + holdout filtering
# --------------------------------------------------------------------------- #
def test_score_run_dir_recurses_worker_ledgers(tmp_path):
    _write_ledger(tmp_path / "w0" / "ledger.jsonl", [_ok_row("a", "w0", 1, 0.40),
                                                     _ok_row("a", "w0", 2, 0.97)])
    _write_ledger(tmp_path / "w1" / "ledger.jsonl", [_ok_row("b", "w1", 1, 0.10)])
    summary = score_run_dir(tmp_path, bar=0.95)
    assert summary.n_tasks == 2
    by_id = {t.task_id: t for t in summary.tasks}
    assert by_id["a"].first_solved_attempt == 2
    assert by_id["b"].solved is False


def test_holdout_filter_reads_real_manifest():
    """The real manifest must expose the held-out NIST set via holdout:true. This
    locks the Rung-0 contract: the scorer can restrict to exactly that set."""
    ho = holdout_task_ids()  # default repo manifest
    assert "nist_ctc_05" in ho
    assert "nist_ftc_07" in ho
    # a solved easy spec part must NOT be in the held-out set
    assert "sample_bracket" not in ho
    assert "bearing_608" not in ho        # round + trivial -> excluded by design


def test_holdout_only_restricts_scoring(tmp_path):
    # one held-out task (nist_ctc_05) + one non-held-out (sample_bracket)
    _write_ledger(tmp_path / "w0" / "ledger.jsonl", [
        _ok_row("nist_ctc_05", "w0", 1, 0.30),
        _ok_row("sample_bracket", "w0", 1, 0.99),
    ])
    full = score_run_dir(tmp_path, bar=0.95, holdout_only=False)
    held = score_run_dir(tmp_path, bar=0.95, holdout_only=True)
    assert full.n_tasks == 2
    assert held.n_tasks == 1
    assert held.tasks[0].task_id == "nist_ctc_05"


def test_default_bar_constant():
    assert DEFAULT_BAR == 0.95


# --------------------------------------------------------------------------- #
#  CLI render + missing-dir guards + JSON contract (review-hardening)
# --------------------------------------------------------------------------- #
def test_render_emits_both_solved_and_unsolved_rows():
    rows = [_ok_row("solved_one", "w", 3, 0.99),
            _ok_row("unsolved_one", "w", 2, 0.10)]
    out = _render(summarize(score_rows(rows, bar=DEFAULT_BAR), bar=DEFAULT_BAR))
    assert "TURNS-TO-SOLVE" in out
    assert "solved_one" in out and "yes" in out and "3" in out
    # the unsolved row renders a dash for turns, not a number
    line = next(ln for ln in out.splitlines() if "unsolved_one" in ln)
    assert "no" in line and "-" in line


def test_render_empty_summary_does_not_crash(tmp_path):
    out = _render(score_run_dir(tmp_path / "definitely_missing", bar=DEFAULT_BAR))
    assert "tasks=0" in out


def test_missing_run_dir_degrades_to_empty(tmp_path):
    missing = tmp_path / "nope"
    assert find_ledgers(missing) == []
    assert read_ledger_rows(missing / "ledger.jsonl") == []
    s = score_run_dir(missing, bar=DEFAULT_BAR)
    assert s.n_tasks == 0
    assert s.solve_rate == 0.0
    assert s.median_turns_to_solve is None


def test_bool_attempt_on_passing_row_reads_unsolved():
    # attempt=True must NOT be treated as attempt 1 even though score crosses the bar
    res = score_rows([{"task_id": "t", "worker": "w", "attempt": True, "score": 0.99}],
                     bar=DEFAULT_BAR)
    assert res["t"].solved is False
    assert res["t"].first_solved_attempt is None
    assert res["t"].best_score == pytest.approx(0.99)


def test_missing_attempt_on_passing_row_reads_unsolved():
    res = score_rows([{"task_id": "t", "worker": "w", "score": 0.99}], bar=DEFAULT_BAR)
    assert res["t"].solved is False
    assert res["t"].first_solved_attempt is None


def test_summary_as_dict_contract_and_sort():
    rows = [_ok_row("zeta", "w", 2, 0.991234), _ok_row("alpha", "w", 1, 0.10)]
    d = summarize(score_rows(rows, bar=DEFAULT_BAR), bar=DEFAULT_BAR).as_dict()
    assert set(d) == {"bar", "n_tasks", "n_solved", "solve_rate",
                      "median_turns_to_solve", "tasks"}
    # nested tasks are sorted by task_id
    assert [t["task_id"] for t in d["tasks"]] == ["alpha", "zeta"]
    z = next(t for t in d["tasks"] if t["task_id"] == "zeta")
    assert set(z) == {"task_id", "solved", "first_solved_attempt",
                      "best_score", "n_attempts", "n_runs", "bar"}
    assert z["best_score"] == 0.9912        # rounded to 4 places


def test_holdout_task_ids_missing_manifest_is_empty(tmp_path):
    assert holdout_task_ids(tmp_path / "no_manifest.yaml") == set()


def test_holdout_only_with_empty_holdout_set_scores_nothing(tmp_path):
    # An empty held-out set must filter EVERYTHING, not silently fall through to
    # scoring all tasks (that would break the locked-eval contract).
    _write_ledger(tmp_path / "w0" / "ledger.jsonl",
                  [_ok_row("sample_bracket", "w0", 1, 0.99)])
    s = score_run_dir(tmp_path, bar=DEFAULT_BAR, holdout_only=True,
                      manifest_path=tmp_path / "no_manifest.yaml")
    assert s.n_tasks == 0


def test_custom_bar_threads_and_flips_solved():
    row = [_ok_row("t", "w", 1, 0.80)]
    low = score_rows(row, bar=0.75)
    high = score_rows(row, bar=0.95)
    assert low["t"].solved is True and low["t"].bar == 0.75
    assert high["t"].solved is False and high["t"].bar == 0.95
    assert summarize(low, bar=0.75).bar == 0.75


def test_summary_median_odd_count_returns_middle_element():
    rows = [_ok_row(f"t{i}", "w", a, 0.99) for i, a in enumerate([2, 4, 6])]
    s = summarize(score_rows(rows, bar=DEFAULT_BAR), bar=DEFAULT_BAR)
    assert s.median_turns_to_solve == pytest.approx(4.0)   # middle element, odd count
