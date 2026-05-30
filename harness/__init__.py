"""CAD autoresearch harness: deterministic execution, grading, rendering, feedback."""
from .runner import run_candidate, RunResult
from .reward import score, RewardConfig, RewardResult
from .render import render_compare
from .feedback import build_report, hints

__all__ = [
    "run_candidate", "RunResult",
    "score", "RewardConfig", "RewardResult",
    "render_compare", "build_report", "hints",
]
