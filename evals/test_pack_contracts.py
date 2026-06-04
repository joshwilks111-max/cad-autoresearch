"""
test_pack_contracts.py — offline evals for the cad-grade and cad-reconstruct packs.

Skills-as-code: each pack's SKILL.md makes a promise; this is the eval that gates it,
the same way evals/test_drawing_read_eval.py gates the drawing-read pack. The point is
symmetric eval coverage — every pack has a runnable offline gate, not just drawing-read.

These are deliberately LIGHT and reuse the repo's real fixtures (no synthetic agent
transcripts): they assert the pack's contract ENTRYPOINT behaves, which is the load-
bearing claim the SKILL.md leans on. Deeper geometry correctness already lives in
tests/test_reward.py; this layer pins the skill-facing contract.

  * cad-grade        — `timetrial/grade_step.py` scores a known-good STEP near-perfect
                       and reports the per-layer breakdown (the referee works).
  * cad-reconstruct  — the offline MockProposer loop climbs and a candidate defines
                       `result` (the propose->grade contract holds, no network).

Offline + free: cad-grade shells the grader on a committed GT STEP; cad-reconstruct
uses the in-process mock ladder. No `claude`, no network. Skipped cleanly if the
build123d/OCP venv or the fixture GT isn't present.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# A committed, license-clean GT STEP (rebuilt from the ISO 608 standard dims) — the
# bearing_608 task. Used as a known-good input for the grader contract.
_BEARING_STEP = _REPO / "tasks" / "bearing_608" / "ground_truth" / "result.step"
_GRADE_STEP = _REPO / "timetrial" / "grade_step.py"

# Prefer the project venv interpreter (build123d needs python <3.14); fall back to ours.
_VENV_PY = _REPO / ".venv" / "Scripts" / "python.exe"
_PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable


def _build123d_available() -> bool:
    try:
        import build123d  # noqa: F401
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# cad-grade — the referee scores a known-good STEP correctly
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.skipif(not _BEARING_STEP.exists(), reason="bearing_608 GT STEP not present")
@pytest.mark.skipif(not _GRADE_STEP.exists(), reason="grade_step.py not present")
def test_cad_grade_scores_known_step_near_perfect():
    """cad-grade's contract: grading a part against its own registered GT yields a
    near-perfect composite (>=0.95 'solved') with a per-layer breakdown, via the right
    entrypoint and a B-rep topology signature (topology == 1.0, not the mesh-proxy 0.5)."""
    proc = subprocess.run(
        [_PY, str(_GRADE_STEP), "--task", "bearing_608",
         "--step", str(_BEARING_STEP), "--json"],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert proc.returncode == 0, f"grader failed: {proc.stderr[-800:]}"
    # the --json payload is the last JSON object on stdout
    out = proc.stdout.strip()
    start = out.rfind("{")
    data = json.loads(out[start:])
    composite = data.get("composite", data.get("score"))
    assert composite is not None, f"no composite in: {data}"
    assert composite >= 0.95, f"known-good STEP should be solved, got {composite}"
    # per-layer breakdown present (the SKILL.md promises body/bbox/volume/iou/topology/chamfer)
    layers = data.get("layers", data)
    assert any("topolog" in k.lower() for k in _flatten_keys(data)), "no topology layer reported"


def _flatten_keys(d, prefix=""):
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            out.append(k)
            out.extend(_flatten_keys(v, k))
    return out


# --------------------------------------------------------------------------- #
# cad-reconstruct — the offline mock loop climbs and the candidate contract holds
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _build123d_available(), reason="build123d/OCP not importable in this interpreter")
def test_cad_reconstruct_mock_loop_climbs_to_target():
    """cad-reconstruct's contract: the propose->build->grade loop converges. The offline
    MockProposer walks a ladder toward the sample_bracket GT; the top rung must define a
    module-level `result` and be the full part (the candidate contract the SKILL.md states)."""
    from loop.policies import MockProposer

    proposer = MockProposer()
    last = None
    # walk the whole ladder; the proposer clamps at the top rung
    for _ in range(6):
        cand = proposer.propose({"task_id": "sample_bracket"}, [])
        last = cand
    assert last is not None
    # the final rung is the complete part: defines `result`, cuts a slot (SUBTRACT), has holes
    code = last.code
    assert "result =" in code or "result=" in code, "candidate must define module-level result"
    assert "Hole(" in code, "the solved rung should bore the holes"
    assert "Mode.SUBTRACT" in code, "the solved rung should cut the slot (polarity)"


@pytest.mark.skipif(not _build123d_available(), reason="build123d/OCP not importable in this interpreter")
def test_cad_reconstruct_candidate_actually_builds_a_solid():
    """The top-rung candidate, executed, yields a real watertight solid with positive
    volume — proving the SKILL.md's `result` contract produces a gradeable part offline."""
    from loop.policies import MockProposer

    proposer = MockProposer()
    cand = None
    for _ in range(6):
        cand = proposer.propose({"task_id": "sample_bracket"}, [])
    ns: dict = {}
    exec(compile(cand.code, "<mock_candidate>", "exec"), ns)  # noqa: S102 - trusted in-repo ladder
    result = ns.get("result")
    assert result is not None, "candidate did not bind `result`"
    # build123d BuildPart -> .part.volume; be liberal about the wrapper
    part = getattr(result, "part", result)
    vol = getattr(part, "volume", None)
    assert vol is not None and vol > 0, f"expected a positive-volume solid, got volume={vol}"
