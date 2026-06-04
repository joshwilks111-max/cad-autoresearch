"""
policies.py — candidate proposers.

A proposer turns (task, history of graded attempts) into the next candidate CAD
program. Two implementations:

  * MockProposer — deterministic, no API, no network. Walks a small ladder of
    hand-written build123d programs that get progressively closer to the sample
    ground truth. Used by the test suite and `--proposer mock` so the entire loop
    (execute -> grade -> render -> keep/discard -> ledger) is exercised offline.

  * ClaudeCodeProposer — shells out to the `claude` CLI in headless/print mode,
    handing it the task spec, the last feedback report, and pointing it at
    program.md. This is what the orchestrator spawns for real runs. Each call is
    one "turn"; the agent may itself spawn subagents (see prompts/) inside the CLI
    process — invisible here.

Both return a `Candidate(code=..., meta=...)`.
"""
from __future__ import annotations

import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from .answer_key_guard import hidden_answer_keys
from .billing import subscription_env


@dataclass
class Candidate:
    code: str
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Mock proposer — offline ladder toward the sample bracket ground truth
# --------------------------------------------------------------------------- #
_MOCK_LADDER = [
    # 0: way off — wrong-size plain box (low IoU, volume over)
    "from build123d import *\nwith BuildPart() as p:\n    Box(120, 80, 20)\nresult = p",
    # 1: right outer plate, no features (bbox close, volume over, topo off)
    "from build123d import *\nwith BuildPart() as p:\n    Box(80, 50, 8)\nresult = p",
    # 2: plate + four holes, missing the central slot
    textwrap.dedent("""
        from build123d import *
        with BuildPart() as p:
            Box(80, 50, 8)
            with Locations((-30, -18, 0), (30, -18, 0), (-30, 18, 0), (30, 18, 0)):
                Hole(radius=2.5)
        result = p
    """).strip(),
    # 3: full part — plate + four holes + central slot (matches ground truth)
    textwrap.dedent("""
        from build123d import *
        with BuildPart() as p:
            Box(80, 50, 8)
            with Locations((-30, -18, 0), (30, -18, 0), (-30, 18, 0), (30, 18, 0)):
                Hole(radius=2.5)
            with BuildSketch():
                SlotOverall(30, 8)
            extrude(amount=-8, mode=Mode.SUBTRACT)
        result = p
    """).strip(),
]


class MockProposer:
    """Returns the next rung of the ladder each call (clamped at the top)."""
    name = "mock"

    def __init__(self):
        self._i = 0

    def propose(self, task: dict, history: list[dict]) -> Candidate:
        code = _MOCK_LADDER[min(self._i, len(_MOCK_LADDER) - 1)]
        self._i += 1
        return Candidate(code=code, meta={"rung": self._i - 1})


# --------------------------------------------------------------------------- #
#  Claude Code proposer — real agent, headless CLI
# --------------------------------------------------------------------------- #
class ClaudeCodeProposer:
    """Drives `claude -p` (print/headless mode). One call == one turn.

    The CLI is pointed at the repo (so it can read program.md, the harness, and
    the task files) and given the latest feedback. We ask it to WRITE the next
    candidate to a known path and echo a sentinel; we then read that file back.

    Requires the Claude Code CLI on PATH, signed in to a plan (`claude login`). NO
    API key is needed: `claude -p` bills the subscription via OAuth. We deliberately
    spawn it with ANTHROPIC_API_KEY removed from the child env (see
    `subscription_env`) — if that var is set, the CLI prefers it and would silently
    bill the metered API, which is exactly what this loop must never do."""
    name = "claude"

    def __init__(self, repo_dir: str | Path, model: str = "opus",
                 cli: str = "claude", turn_timeout: int = 600,
                 allowed_tools: str = "Read,Write,Edit,Bash,Glob,Grep,Task"):
        self.repo_dir = Path(repo_dir)
        self.model = model
        self.cli = cli
        self.turn_timeout = turn_timeout
        self.allowed_tools = allowed_tools

    def propose(self, task: dict, history: list[dict]) -> Candidate:
        ws = Path(task["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        target = ws / "candidate.py"
        last = history[-1]["feedback_markdown"] if history else "(first attempt)"

        prompt = textwrap.dedent(f"""
            Read ./program.md and follow it exactly. You are working on task
            '{task['task_id']}'.

            TASK SPEC: {task['spec_path']}
            {"DRAWING IMAGE: " + task['drawing_path'] if task.get('drawing_path') else ""}
            GROUND TRUTH is hidden from you; the harness grades you against it.

            Best composite score so far on this task: {task.get('best', -1):.3f}

            FEEDBACK FROM YOUR LAST ATTEMPT:
            {last}

            Produce the NEXT candidate. Write the complete build123d program to:
                {target}
            The program MUST assign the final solid to a variable named `result`.
            Do not run the grader yourself. When the file is written, print the
            single line: CANDIDATE_WRITTEN
        """).strip()

        cmd = [self.cli, "-p", prompt, "--model", self.model,
               "--permission-mode", "acceptEdits",
               "--allowedTools", self.allowed_tools]
        try:
            # Two protections wrap this single spawn:
            #  1. env scrub: drop ANTHROPIC_API_KEY so `claude -p` bills the
            #     subscription (OAuth) and never the metered API (loop/billing.py).
            #  2. answer-key guard: the worker's cwd IS the repo root, so the
            #     dimension/score answer-keys (evals/fixtures/*/expected_dims.json,
            #     tasks/*/.best_score, tasks/*/best_candidate.py) would be a
            #     Read/Grep-able answer key. `--allowedTools` can't path-scope Read,
            #     so we move them out of the worker-resolvable tree for the duration
            #     of the turn and restore them after (loop/answer_key_guard.py).
            with hidden_answer_keys(self.repo_dir):
                proc = subprocess.run(cmd, cwd=str(self.repo_dir), capture_output=True,
                                      text=True, timeout=self.turn_timeout,
                                      env=subscription_env())
        except subprocess.TimeoutExpired:
            return Candidate(code="", meta={"error": "cli_timeout"})

        if not target.exists():
            return Candidate(code="", meta={"error": "no_candidate_written",
                                            "stdout_tail": proc.stdout[-500:],
                                            "stderr_tail": proc.stderr[-500:]})
        return Candidate(code=target.read_text(),
                         meta={"cli_returncode": proc.returncode})


def make_proposer(kind: str, **kw):
    if kind == "mock":
        return MockProposer()
    if kind == "claude":
        return ClaudeCodeProposer(**kw)
    raise ValueError(f"unknown proposer kind: {kind}")
