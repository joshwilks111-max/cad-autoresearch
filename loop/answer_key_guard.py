"""
answer_key_guard.py — make the dimension/score answer-keys structurally unreadable
to a spawned worker for the duration of its `claude -p` turn.

THE LEAK (review finding #1, CRITICAL). A worker proposer is spawned with
`allowed_tools="Read,Write,Edit,Bash,Glob,Grep,Task"` and `cwd = repo root`
(see `loop/policies.py`). That means several repo-relative paths are a readable
*answer key* the worker could `Read`/`Grep` (or read via a `Task` subagent):

  * evals/fixtures/**/expected_dims.json   — the hand-authored dimension key the
                                             drawing-read eval scores against.
  * tasks/*/.best_score                     — the best composite score so far.
  * tasks/*/best_candidate.py               — the best candidate program so far
                                             (the strongest possible answer key).

`claude -p --allowedTools` can allow/deny a *tool*, not a *path* — you cannot say
"Read, but not these files". `.gitignore` does not help either: a gitignored file
still exists on disk and is readable by `Read`. So the only robust enforcement is
to make the bytes **not resolvable from the worker's cwd** while the worker runs.

THE GUARD. `hidden_answer_keys(repo_root)` is a context manager that, on enter,
moves each existing answer-key path to a sibling staging directory OUTSIDE the
repo root (so it cannot be reached by any repo-relative path the worker tries),
and on exit — including on exception — moves every one back to its exact original
location. The repo tree the worker sees during its turn simply does not contain
the keys.

CONCURRENCY — FAIL CLOSED (the /review fix, 2026-06-04). An independent review
(Codex + Claude adversarial, both reproduced the leak) showed the original guard
was UNSAFE the way the loop actually runs: `orchestrator.py` defaults to 4 workers,
all spawning `claude -p` from the SAME repo checkout, all calling this guard on the
SAME answer-key paths. Two failure modes were reproduced:

  1. Worker A hides keys; worker B enters while A is live, sees nothing to hide, and
     starts its turn. When A exits it restores the keys to the repo WHILE B is still
     mid-turn — B can now read them. (concurrent same-checkout scopes)
  2. `restore_orphaned` (the watcher/orchestrator startup sweep) moves staged keys
     back into the repo WHILE a worker holds a live scope — re-exposing them. (36
     leak events reproduced from the documented `orchestrator.py && watcher.py` flow.)

Rather than build a full cross-process refcount (restore only when the LAST worker
exits) — which the single-worker workflow does not need — this guard FAILS CLOSED:

  * Each active scope writes a PID lockfile under the staging dir.
  * On enter, if ANY OTHER live scope's lock exists, we raise `AnswerKeyGuardBusy`
    BEFORE moving anything. A worker that cannot safely hide the keys does not run —
    it never leaks. The grid run fails loudly with an actionable message instead of
    silently leaking; serialize the workers or give each its own checkout/worktree.
  * `restore_orphaned` REFUSES to sweep while any live scope's lock exists, so the
    watcher startup can no longer yank keys out from under a live worker. It only
    recovers keys orphaned by a DEAD scope (hard kill), which is its real job.

DESIGN NOTES
  * Out-of-repo, not /tmp-on-another-volume: we relocate into
    `<repo_root>/../.cad-answer-keys-hidden/` so the move is a cheap same-volume
    rename on Windows (os.replace) where possible. It is a *sibling* of the repo,
    never inside it, so it is never on a worker-resolvable repo-relative path.
  * Cross-device fallback: if `<repo>/..` resolves to a different volume (mount
    point, `subst`, mapped/network drive), `os.replace` raises `OSError(EXDEV)`.
    We fall back to `shutil.move` (copy-then-delete) so the guard degrades instead
    of bricking the loop with a raw EXDEV.
  * Atomic hide: the move loop runs INSIDE the `try`, so a mid-loop failure restores
    every already-moved key in the `finally` (no keys stranded out-of-repo).
  * finally-restore: the restore runs in a `finally`, so a crashed/killed turn
    still puts the keys back. If the process is hard-killed mid-turn, the keys are
    recoverable from the staging dir (the startup sweep `restore_orphaned`).

Used by:
  * loop/policies.py  (ClaudeCodeProposer.propose — wraps the `claude -p` spawn)
  * orchestrator.py / watcher.py  (restore_orphaned startup sweep)
"""
from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

# Repo-relative globs whose resolved files are answer-keys the worker must not read.
# Kept here as the single source of truth so a new key class is one edit.
ANSWER_KEY_GLOBS: tuple[str, ...] = (
    "evals/fixtures/*/expected_dims.json",
    "tasks/*/.best_score",
    "tasks/*/best_candidate.py",
)

# Sibling-of-repo staging dir name (created next to the repo root, never inside it).
_STAGING_DIRNAME = ".cad-answer-keys-hidden"
# Per-scope PID lockfiles live here so concurrent scopes / the restore sweep can
# detect a live owner. Prefix lets us glob them without catching staged keys.
_LOCK_PREFIX = ".scope-"
_LOCK_SUFFIX = ".lock"


class AnswerKeyGuardBusy(RuntimeError):
    """Raised on enter when another LIVE guard scope already owns this checkout.

    Fail-closed: we move nothing and refuse to run, rather than hide nothing and let
    the worker read the keys (or let a concurrent restore re-expose them). The caller
    (policies.py) treats this as a skipped turn, not a crash.
    """


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID is running. psutil when available (clean,
    cross-platform, PID-reuse aware enough for our purpose); os.kill(pid, 0) fallback."""
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:
        pass
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    except OSError:
        # Windows: errno EINVAL (22) for a dead PID; anything else -> assume gone.
        return False
    return True


def _staging_dir(repo_root: Path) -> Path:
    """The out-of-repo staging directory (sibling of the repo root)."""
    return repo_root.resolve().parent / _STAGING_DIRNAME


def _live_locks(staging: Path, *, exclude_pid: int | None = None) -> list[Path]:
    """Lockfiles under staging whose owning PID is still alive. Dead-PID locks are
    swept (removed) as a side effect so a hard-killed scope never blocks forever."""
    live: list[Path] = []
    if not staging.exists():
        return live
    for lock in staging.glob(f"{_LOCK_PREFIX}*{_LOCK_SUFFIX}"):
        try:
            pid = int(lock.stem[len(_LOCK_PREFIX):])
        except ValueError:
            continue
        if exclude_pid is not None and pid == exclude_pid:
            continue
        if _pid_alive(pid):
            live.append(lock)
        else:
            # stale lock from a dead scope — clear it so it can't block forever.
            with contextlib.suppress(OSError):
                lock.unlink()
    return live


def discover_answer_keys(repo_root: Path | str) -> list[Path]:
    """Every existing answer-key file under the repo (resolved, absolute).

    Pure discovery — no mutation. Used by the guard and by tests that assert the
    leak surface is what we think it is.
    """
    root = Path(repo_root).resolve()
    found: list[Path] = []
    for pattern in ANSWER_KEY_GLOBS:
        for p in root.glob(pattern):
            if p.is_file():
                found.append(p.resolve())
    return sorted(found)


def _rel_to_repo(repo_root: Path, p: Path) -> Path:
    """The repo-relative path of an answer key, used to mirror it in staging."""
    return p.resolve().relative_to(repo_root.resolve())


def _move(src: Path, dst: Path) -> None:
    """Move src -> dst, atomic within a volume (os.replace), falling back to a
    copy-then-delete across volumes (EXDEV) so a split-volume layout degrades
    instead of bricking the loop."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        # Cross-device (EXDEV) or similar: shutil.move handles copy+unlink.
        shutil.move(str(src), str(dst))


@contextlib.contextmanager
def hidden_answer_keys(repo_root: Path | str):
    """Context manager: hide answer-keys out of the worker-resolvable tree for the
    scope, restore them (always) on exit. FAILS CLOSED on concurrent same-checkout use.

    On enter:
      * if another LIVE scope owns this checkout, raise AnswerKeyGuardBusy (move nothing).
      * else write this scope's PID lock, then move each discovered answer-key to
        `<repo>/../.cad-answer-keys-hidden/`, preserving its repo-relative subpath.
    On exit (incl. exception): move every hidden key back, then drop our PID lock.

    Yields the list of original paths that were hidden, for logging/asserting.
    """
    root = Path(repo_root).resolve()
    staging = _staging_dir(root)

    # Fail closed: refuse if another live scope already owns this checkout.
    if _live_locks(staging):
        raise AnswerKeyGuardBusy(
            f"another live answer-key guard scope owns {root} — refusing to run "
            f"(serialize workers or give each its own checkout/worktree)"
        )

    staging.mkdir(parents=True, exist_ok=True)
    my_lock = staging / f"{_LOCK_PREFIX}{os.getpid()}{_LOCK_SUFFIX}"
    my_lock.write_text(str(root), encoding="utf-8")

    moved: list[tuple[Path, Path]] = []  # (original, hidden)
    try:
        for original in discover_answer_keys(root):
            rel = _rel_to_repo(root, original)
            hidden = staging / rel
            _move(original, hidden)
            moved.append((original, hidden))
        yield [orig for orig, _ in moved]
    finally:
        for original, hidden in moved:
            if hidden.exists():
                _move(hidden, original)
        with contextlib.suppress(OSError):
            my_lock.unlink()
        # tidy the (now-empty) staging tree; ignore if anything still lingers
        # (e.g. another scope's lock — never rmdir a dir that still has content).
        _tidy_staging(staging)


def _tidy_staging(staging: Path) -> None:
    """Remove empty subdirs of staging bottom-up. Never removes a dir that still
    holds files (a live lock, or another scope's staged keys)."""
    with contextlib.suppress(OSError):
        for dirpath, dirnames, filenames in os.walk(staging, topdown=False):
            if not dirnames and not filenames:
                os.rmdir(dirpath)


def restore_orphaned(repo_root: Path | str) -> list[Path]:
    """Startup sweep: if a previous run was hard-killed mid-turn, answer-keys may be
    stranded in the staging dir. Move any stranded key back to its repo-relative home.

    REFUSES to run while any LIVE scope owns the checkout (the /review fix): the watcher
    startup must not yank keys back out from under a worker mid-turn. Returns the list of
    restored original paths (empty if nothing staged OR a live scope blocks the sweep).
    Safe to call when nothing is staged.
    """
    root = Path(repo_root).resolve()
    staging = _staging_dir(root)
    if not staging.exists():
        return []
    # A live scope is legitimately holding keys hidden — do NOT re-expose them.
    if _live_locks(staging):
        return []
    restored: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(staging):
        for fn in filenames:
            # skip lockfiles (only dead ones remain past the _live_locks check)
            if fn.startswith(_LOCK_PREFIX) and fn.endswith(_LOCK_SUFFIX):
                with contextlib.suppress(OSError):
                    (Path(dirpath) / fn).unlink()
                continue
            hidden = Path(dirpath) / fn
            rel = hidden.resolve().relative_to(staging.resolve())
            original = root / rel
            _move(hidden, original)
            restored.append(original)
    _tidy_staging(staging)
    return sorted(restored)
