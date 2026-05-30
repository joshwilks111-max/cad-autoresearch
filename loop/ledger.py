"""
ledger.py — the experiment ledger.

Every attempt across every worker appends one JSON line: task, candidate code
hash, full score breakdown, keep/discard decision, timing. This is the
autoresearch lab notebook — it lets you (and any outer/meta agent) see what was
tried, what improved, and where the search is stuck. `best()` powers the
keep/discard acceptance rule. Thread- and process-safe via append-only writes.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._best: dict[str, float] = {}
        if self.path.exists():
            self._warm_start()

    def _warm_start(self):
        for line in self.path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t, s = rec.get("task_id"), rec.get("score", 0.0)
            if rec.get("kept") and (t not in self._best or s > self._best[t]):
                self._best[t] = s

    @staticmethod
    def code_hash(code: str) -> str:
        return hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]

    def best(self, task_id: str) -> float:
        return self._best.get(task_id, -1.0)

    def consider(self, task_id: str, score: float, *, min_delta: float = 0.0) -> bool:
        """Keep/discard acceptance: accept iff score beats best-so-far by at least
        `min_delta`. Updates best-so-far on accept."""
        with self._lock:
            prev = self._best.get(task_id, -1.0)
            if score > prev + min_delta:
                self._best[task_id] = score
                return True
            return False

    def log(self, *, task_id: str, worker: str, attempt: int, code: str,
            score: float, breakdown: dict, kept: bool, seconds: float,
            error: str | None = None, extra: dict | None = None):
        rec = {
            "ts": time.time(), "task_id": task_id, "worker": worker,
            "attempt": attempt, "code_hash": self.code_hash(code),
            "code_len": len(code), "score": round(float(score), 4),
            "breakdown": breakdown, "kept": bool(kept),
            "seconds": round(float(seconds), 2), "error": error,
        }
        if extra:
            rec.update(extra)
        with self._lock:
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        return rec

    def leaderboard(self) -> dict[str, float]:
        with self._lock:
            return dict(sorted(self._best.items(), key=lambda kv: -kv[1]))
