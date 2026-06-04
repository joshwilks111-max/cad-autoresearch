"""
answer_key_guard.py — make the dimension/score answer-keys structurally unreadable
to a spawned worker for the duration of its `claude -p` turn.

THE LEAK (review finding #1, CRITICAL). A worker proposer is spawned with
`allowed_tools="Read,Write,Edit,Bash,Glob,Grep,Task"` and `cwd = repo root`
(see `loop/policies.py`). That means three repo-relative paths are a readable
*answer key* the worker could `Read`/`Grep` (or read via a `Task` subagent):

  * evals/fixtures/**/expected_dims.json   — the hand-authored dimension key the
                                             drawing-read eval scores against.
  * tasks/*/.best_score                     — the best composite score so far.
  * tasks/*/best_candidate.py               — the best candidate program so far.

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

DESIGN NOTES
  * Out-of-repo, not /tmp-on-another-volume: we relocate into
    `<repo_root>/../.cad-answer-keys-hidden/` so the move is a cheap same-volume
    rename on Windows (os.replace), not a cross-device copy. It is a *sibling* of
    the repo, never inside it, so it is never on a worker-resolvable repo-relative
    path.
  * finally-restore: the restore runs in a `finally`, so a crashed/killed turn
    still puts the keys back. If the process is hard-killed mid-turn, the keys are
    recoverable from the staging dir (a startup sweep, `restore_orphaned`, puts
    any stranded keys back).
  * CONCURRENCY — one active scope per checkout. This guard is NOT safe against two
    `hidden_answer_keys` scopes running concurrently on the SAME repo checkout: both
    would `os.replace` the same key paths, and the second to enter finds nothing to
    hide (so it restores nothing) while the moves can clobber or raise. That is fine
    for how the loop runs today — a single worker proposes one turn at a time, so a
    given checkout has at most one guarded `claude -p` spawn in flight. The grid
    fans out workers, but each worker gets its own run directory; if you ever point
    two workers at the SAME repo checkout and let their turns overlap, serialize them
    externally (or give each its own checkout). A `<staging>/.lock` + refcount could
    make same-checkout concurrency safe, but it is deliberately NOT built until that
    case is real — the startup `restore_orphaned` sweep already recovers a checkout
    left mid-move by a crash.

Used by:
  * loop/policies.py  (ClaudeCodeProposer.propose — wraps the `claude -p` spawn)
"""
from __future__ import annotations

import contextlib
import os
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


def _staging_dir(repo_root: Path) -> Path:
    """The out-of-repo staging directory (sibling of the repo root)."""
    return repo_root.resolve().parent / _STAGING_DIRNAME


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


@contextlib.contextmanager
def hidden_answer_keys(repo_root: Path | str):
    """Context manager: hide answer-keys out of the worker-resolvable tree for the
    scope, restore them (always) on exit.

    On enter: move each discovered answer-key to `<repo>/../.cad-answer-keys-hidden/`,
    preserving its repo-relative subpath so restore is unambiguous.
    On exit (incl. exception): move every hidden key back to its original location.

    Yields the list of (original_path) that were hidden, for logging/asserting.
    """
    root = Path(repo_root).resolve()
    staging = _staging_dir(root)
    keys = discover_answer_keys(root)

    moved: list[tuple[Path, Path]] = []  # (original, hidden)
    if keys:
        staging.mkdir(parents=True, exist_ok=True)
        for original in keys:
            rel = _rel_to_repo(root, original)
            hidden = staging / rel
            hidden.parent.mkdir(parents=True, exist_ok=True)
            # os.replace is atomic within a volume and overwrites a stale target.
            os.replace(original, hidden)
            moved.append((original, hidden))
    try:
        yield [orig for orig, _ in moved]
    finally:
        for original, hidden in moved:
            if hidden.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                os.replace(hidden, original)
        # tidy the (now-empty) staging tree; ignore if anything still lingers.
        with contextlib.suppress(OSError):
            for dirpath, dirnames, filenames in os.walk(staging, topdown=False):
                if not dirnames and not filenames:
                    os.rmdir(dirpath)


def restore_orphaned(repo_root: Path | str) -> list[Path]:
    """Startup sweep: if a previous run was hard-killed mid-turn, answer-keys may be
    stranded in the staging dir. Move any stranded key back to its repo-relative home.
    Returns the list of restored original paths. Safe to call when nothing is staged.
    """
    root = Path(repo_root).resolve()
    staging = _staging_dir(root)
    if not staging.exists():
        return []
    restored: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(staging):
        for fn in filenames:
            hidden = Path(dirpath) / fn
            rel = hidden.resolve().relative_to(staging.resolve())
            original = root / rel
            original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(hidden, original)
            restored.append(original)
    with contextlib.suppress(OSError):
        for dp, dn, fns in os.walk(staging, topdown=False):
            if not dn and not fns:
                os.rmdir(dp)
    return sorted(restored)
