"""
test_answer_key_guard.py — prove the fixture/score answer-keys are unreadable from
the worker's cwd while a turn runs (review finding #1 acceptance criterion).

The worker is spawned with cwd = repo root and Read/Grep/Task. These tests build a
throwaway repo-shaped tree, then assert that INSIDE `hidden_answer_keys(repo)` the
answer-key paths do not resolve from the repo root (a `Read repo/evals/fixtures/..`
finds nothing), and that AFTER the scope every key is back, byte-for-byte, where it
was — including when the body raises.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from loop.answer_key_guard import (  # noqa: E402
    ANSWER_KEY_GLOBS,
    discover_answer_keys,
    hidden_answer_keys,
    restore_orphaned,
)


def _make_repo(tmp_path: Path) -> dict[str, Path]:
    """Build a minimal repo-shaped tree with one of each answer-key class + decoys."""
    repo = tmp_path / "repo"
    (repo / "evals" / "fixtures" / "nist_ctc_03").mkdir(parents=True)
    (repo / "evals" / "fixtures" / "trial_lbracket").mkdir(parents=True)
    (repo / "tasks" / "nist_ctc_03").mkdir(parents=True)

    keys = {
        "fixture_a": repo / "evals" / "fixtures" / "nist_ctc_03" / "expected_dims.json",
        "fixture_b": repo / "evals" / "fixtures" / "trial_lbracket" / "expected_dims.json",
        "best_score": repo / "tasks" / "nist_ctc_03" / ".best_score",
        "best_candidate": repo / "tasks" / "nist_ctc_03" / "best_candidate.py",
    }
    keys["fixture_a"].write_text('{"units":"mm","nominal":25.4}')
    keys["fixture_b"].write_text('{"units":"mm","nominal":120.0}')
    keys["best_score"].write_text("0.873")
    keys["best_candidate"].write_text("result = None  # best so far")

    # decoys that must NEVER be hidden (a readable, legitimate file the worker needs)
    decoy = repo / "evals" / "fixtures" / "nist_ctc_03" / "extracted.json"
    decoy.write_text('{"a":1}')  # not expected_dims.json -> not a key
    program = repo / "program.md"
    program.write_text("# worker manual")
    return {"repo": repo, "decoy": decoy, "program": program, **keys}


def test_discovers_every_answer_key_class(tmp_path):
    t = _make_repo(tmp_path)
    found = set(discover_answer_keys(t["repo"]))
    assert t["fixture_a"].resolve() in found
    assert t["fixture_b"].resolve() in found
    assert t["best_score"].resolve() in found
    assert t["best_candidate"].resolve() in found
    # decoys excluded
    assert t["decoy"].resolve() not in found
    assert t["program"].resolve() not in found


def test_keys_unreadable_inside_scope_restored_after(tmp_path):
    t = _make_repo(tmp_path)
    repo = t["repo"]

    # all keys readable before
    assert t["fixture_a"].exists()

    with hidden_answer_keys(repo) as hidden:
        # every key class is gone from its repo-relative path mid-scope
        assert not t["fixture_a"].exists(), "fixture must be hidden during the turn"
        assert not t["best_score"].exists(), ".best_score must be hidden"
        assert not t["best_candidate"].exists(), "best_candidate.py must be hidden"
        # a worker globbing the repo finds NO answer keys
        assert discover_answer_keys(repo) == []
        # the guard yields the ORIGINAL paths it hid; assert it hid all four classes
        assert set(p.resolve() for p in hidden) == {
            t["fixture_a"].resolve(), t["fixture_b"].resolve(),
            t["best_score"].resolve(), t["best_candidate"].resolve(),
        }
        # the bytes now live in a SIBLING-of-repo staging dir, never inside the repo
        staging = repo.resolve().parent / ".cad-answer-keys-hidden"
        assert staging.exists() and repo.resolve() not in staging.parents
        # decoys remain readable (we only hid the keys)
        assert t["decoy"].exists()
        assert t["program"].exists()

    # everything back, byte-for-byte, after the scope
    assert t["fixture_a"].read_text() == '{"units":"mm","nominal":25.4}'
    assert t["best_score"].read_text() == "0.873"
    assert t["best_candidate"].read_text() == "result = None  # best so far"
    assert set(discover_answer_keys(repo)) == {
        t["fixture_a"].resolve(), t["fixture_b"].resolve(),
        t["best_score"].resolve(), t["best_candidate"].resolve(),
    }


def test_keys_restored_even_when_body_raises(tmp_path):
    t = _make_repo(tmp_path)
    repo = t["repo"]

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with hidden_answer_keys(repo):
            assert not t["fixture_a"].exists()  # hidden
            raise Boom("worker turn blew up mid-spawn")

    # finally-restore put it back despite the exception
    assert t["fixture_a"].exists()
    assert t["fixture_a"].read_text() == '{"units":"mm","nominal":25.4}'


def test_restore_orphaned_recovers_a_hard_killed_turn(tmp_path):
    """Simulate a hard kill: keys left in staging, process gone. The startup sweep
    must move them back."""
    t = _make_repo(tmp_path)
    repo = t["repo"]

    # enter the guard manually and DON'T exit cleanly (simulate kill -9): call
    # __enter__ to hide, then abandon the cm without ever calling __exit__.
    cm = hidden_answer_keys(repo)
    cm.__enter__()  # keys now hidden; no __exit__ -> no restore (a hard kill)
    assert not t["fixture_a"].exists()

    # keys are stranded in staging; the worker-resolvable tree has none
    assert discover_answer_keys(repo) == []

    restored = restore_orphaned(repo)
    assert t["fixture_a"].resolve() in {p.resolve() for p in restored}
    assert t["fixture_a"].exists()
    assert t["fixture_a"].read_text() == '{"units":"mm","nominal":25.4}'


def test_noop_when_no_keys_present(tmp_path):
    """A repo with no answer-keys yet (fresh checkout) must enter/exit cleanly."""
    repo = tmp_path / "empty_repo"
    (repo / "evals").mkdir(parents=True)
    with hidden_answer_keys(repo) as hidden:
        assert hidden == []
    assert restore_orphaned(repo) == []


def test_glob_constant_covers_the_three_documented_classes():
    """Lock the leak surface: if someone adds a key class, this test forces them to
    update ANSWER_KEY_GLOBS (and think about the guard)."""
    assert "evals/fixtures/*/expected_dims.json" in ANSWER_KEY_GLOBS
    assert "tasks/*/.best_score" in ANSWER_KEY_GLOBS
    assert "tasks/*/best_candidate.py" in ANSWER_KEY_GLOBS
