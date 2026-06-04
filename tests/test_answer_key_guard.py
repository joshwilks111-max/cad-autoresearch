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
    AnswerKeyGuardBusy,
    _LOCK_PREFIX,
    _LOCK_SUFFIX,
    _staging_dir,
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
    """Simulate a hard kill: keys left in staging, the OWNING PROCESS IS GONE. The
    startup sweep must move them back.

    Fidelity note (/review fix): a real hard kill means the scope's PID is DEAD. The
    guard's liveness gate refuses to sweep while a LIVE-PID lock exists (so the watcher
    can't yank keys from a running worker), so this test forges the lock to a dead PID —
    which is what kill -9 actually leaves behind. (Leaving the test-runner's own live PID
    in the lock would correctly be refused; see
    test_restore_orphaned_refuses_while_a_live_scope_owns_the_checkout.)"""
    t = _make_repo(tmp_path)
    repo = t["repo"]

    # enter the guard manually and DON'T exit cleanly (simulate kill -9): call
    # __enter__ to hide, then abandon the cm without ever calling __exit__.
    cm = hidden_answer_keys(repo)
    cm.__enter__()  # keys now hidden; no __exit__ -> no restore (a hard kill)
    assert not t["fixture_a"].exists()
    assert discover_answer_keys(repo) == []  # stranded in staging

    # a real hard kill leaves a DEAD-PID lock — forge it so the sweep treats the
    # owning scope as gone (the live test-runner PID would correctly be refused).
    staging = _staging_dir(repo)
    for lk in staging.glob(f"{_LOCK_PREFIX}*{_LOCK_SUFFIX}"):
        lk.unlink()
    (staging / f"{_LOCK_PREFIX}999999{_LOCK_SUFFIX}").write_text(str(repo))

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


# --- /review fixes: fail-closed concurrency + sweep liveness + atomic hide ---


def test_concurrent_scope_fails_closed_and_leaves_first_scope_intact(tmp_path):
    """The CRITICAL leak: while one scope owns the checkout, a second scope must REFUSE
    (raise AnswerKeyGuardBusy) and move NOTHING — never hide-nothing-and-let-worker-read.
    The first scope's hidden keys must stay hidden across the refusal."""
    t = _make_repo(tmp_path)
    repo = t["repo"]

    with hidden_answer_keys(repo):
        assert not t["fixture_a"].exists()  # scope 1 hid the keys
        # scope 2 on the SAME checkout must fail closed, not silently run
        with pytest.raises(AnswerKeyGuardBusy):
            with hidden_answer_keys(repo):
                pass  # must not reach here
        # scope 1's keys are STILL hidden (scope 2 didn't restore/clobber them)
        assert not t["fixture_a"].exists()
        assert discover_answer_keys(repo) == []
    # after scope 1 exits cleanly, everything is back
    assert t["fixture_a"].read_text() == '{"units":"mm","nominal":25.4}'


def test_restore_orphaned_refuses_while_a_live_scope_owns_the_checkout(tmp_path):
    """The watcher-startup CRITICAL: restore_orphaned must NOT yank keys back into the
    repo while a worker holds a live scope (that re-exposes the answer key mid-turn)."""
    t = _make_repo(tmp_path)
    repo = t["repo"]

    with hidden_answer_keys(repo):
        assert not t["fixture_a"].exists()  # live scope holds keys hidden
        # simulate the watcher's unconditional startup sweep firing mid-turn
        restored = restore_orphaned(repo)
        assert restored == [], "sweep must refuse while a live scope owns the checkout"
        # the key is STILL hidden — not re-exposed to the live worker
        assert not t["fixture_a"].exists()
        assert discover_answer_keys(repo) == []
    # normal restore on scope exit still works
    assert t["fixture_a"].exists()


def test_restore_orphaned_recovers_keys_left_by_a_DEAD_scope(tmp_path):
    """The legitimate job: a hard-killed scope leaves a stale (dead-PID) lock + staged
    keys. restore_orphaned must clear the dead lock and recover the keys."""
    t = _make_repo(tmp_path)
    repo = t["repo"]

    cm = hidden_answer_keys(repo)
    cm.__enter__()  # hide; never __exit__ (hard kill)
    assert not t["fixture_a"].exists()

    # forge the lock to a guaranteed-dead PID so the sweep treats the scope as dead
    staging = _staging_dir(repo)
    for lk in staging.glob(f"{_LOCK_PREFIX}*{_LOCK_SUFFIX}"):
        lk.unlink()
    (staging / f"{_LOCK_PREFIX}999999{_LOCK_SUFFIX}").write_text(str(repo))

    restored = restore_orphaned(repo)
    assert t["fixture_a"].resolve() in {p.resolve() for p in restored}
    assert t["fixture_a"].exists()
    # the dead lock was cleared
    assert list(staging.glob(f"{_LOCK_PREFIX}*{_LOCK_SUFFIX}")) == []


def test_partial_hide_failure_restores_already_moved_keys(tmp_path, monkeypatch):
    """The stranding HIGH: if a move raises mid-hide, the finally must restore every
    already-moved key (none stranded out-of-repo). The hide loop is inside the try."""
    import loop.answer_key_guard as g

    t = _make_repo(tmp_path)
    repo = t["repo"]

    real_move = g._move
    calls = {"n": 0}

    def flaky_move(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # let the first key hide, blow up on the second
            raise OSError("simulated mid-hide failure")
        return real_move(src, dst)

    monkeypatch.setattr(g, "_move", flaky_move)

    with pytest.raises(OSError):
        with hidden_answer_keys(repo):
            pass

    # every key is back in the repo — none stranded in staging
    assert set(discover_answer_keys(repo)) == {
        t["fixture_a"].resolve(), t["fixture_b"].resolve(),
        t["best_score"].resolve(), t["best_candidate"].resolve(),
    }


def test_cross_device_move_falls_back_to_copy(tmp_path, monkeypatch):
    """The EXDEV HIGH: if os.replace raises (cross-device), _move falls back to
    shutil.move so the guard degrades instead of bricking the loop."""
    import loop.answer_key_guard as g

    t = _make_repo(tmp_path)
    repo = t["repo"]

    def replace_always_exdev(src, dst):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(g.os, "replace", replace_always_exdev)

    # hide + restore must still work via the shutil.move fallback
    with hidden_answer_keys(repo):
        assert not t["fixture_a"].exists()
    assert t["fixture_a"].read_text() == '{"units":"mm","nominal":25.4}'
