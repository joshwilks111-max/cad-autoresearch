# Time Trial — human vs AI on a real CAD part (RESULTS)

> **STATUS: scaffold.** The toolkit, the part, and the referee are built and self-tested.
> The timed human-vs-AI run is pending (it needs a human modeller + a fresh AI session so
> neither has seen the ground truth — see `PROTOCOL.md`). The numbers below fill in from
> `timetrial/results.jsonl` via `python timetrial/trial.py aggregate` — they are **computed,
> never hand-typed**, so the headline can't drift from the artifacts.

## The claim this answers
Tim: *"There's no harness for AI tools to do CAD and double engineer productivity."* The
honest, defensible rebuttal — not a property-checklist, not a benchmark score:

> The hard part of AI CAD, the part every demo fakes, is **knowing when the output is
> actually correct**. This repo is an open, deterministic geometric referee an agent
> self-corrects against. In a head-to-head time trial on a real part, the AI loop reaches a
> **referee-verified-correct** solid in `<RATIO>`× the human's wall-clock — and absorbs a
> revision by changing one number.

## Verify it yourself in ~2 minutes (don't trust this file)
```
# setup once (build123d needs Python < 3.14):
uv venv --python 3.13 && uv pip install -r requirements.txt
# then:
./timetrial/verify.sh        # (Windows: .\timetrial\verify.ps1)
```
That re-grades the committed STEPs from disk through the same referee and prints the
headline. **Zero-Python path:** open `timetrial/artifacts/human_build.step` and
`ai_build.step` in ANY CAD viewer (FreeCAD, the free online viewers) and eyeball them
against `tasks/trial_lbracket/drawing.png`. The STEPs are real B-rep solids.

## Pre-registration (fixed BEFORE the run — `protocol.yaml`)
- **Part:** `trial_lbracket` — gusseted L-bracket, 120×60×44 mm, ~17 B-rep faces, prismatic.
  Forward-authored as design intent (`tasks/trial_lbracket/spec.md`) then compiled to ground
  truth — license-clean, not reverse-engineered. Chosen as a fair fight: not a trivial 4-face
  washer, not a topology-capped 150-face NIST part; ~5-10 min of genuine human CAD.
- **Input:** both competitors get only `drawing.png` (drawing track). Neither opens
  `ground_truth/` or `spec.md`.
- **Verified-correct bar:** composite ≥ 0.95, via `timetrial/grade_step.py` (the one referee).
- **Primary metric:** turns-to-verified (deterministic). **Secondary:** end-to-end wall-clock
  (AI includes inference + operator latency — biased *against* the AI).
- **Revision:** base bolt-hole X-spacing 90 → 98 mm (pre-registered, same for both sides).

## Results
<!-- AUTO: paste the output of `python timetrial/trial.py aggregate` here, or read results_table.md -->
_(pending the timed run — `timetrial/trial.py aggregate` writes `results_table.md`)_

## The three reflexes a skeptic will have — answered up front
1. **"You cherry-picked the part."** It's pre-registered (above), forward-authored before any
   run, mid-complexity and prismatic by stated criteria, not picked to flatter the AI. It's
   also n=1 — an existence proof you can reproduce, not a statistic. Swap in your own part via
   `grade_step.py --ref your_reference.step --step candidate.step`.
2. **"The AI had the answer key."** No. The trial strips the AI to pass/fail + its own renders
   (PROTOCOL.md §2); the GT-revealing `grade_one.py` feedback (GT renders + volume/bbox/topo
   deltas) is forbidden during the trial. Both sides see only the drawing.
3. **"Your timer is fake."** Primary metric is turns-to-verified (deterministic, in the
   ledger). Wall-clock is end-to-end and conservative against the AI (includes inference). The
   committed STEPs let you re-grade and re-time independently.

## Honest limitations (what this does NOT prove)
- **The referee needs ground truth → this is a DEMONSTRATION, not a production claim.** In real
  work the engineer has no answer-key STEP. This shows the AI reaches a *verifiable-correct*
  part fast on a part we CAN verify. Verifying without GT (against the spec/drawing, or human
  acceptance) is the deferred next step.
- **n=1.** One part, one human, one AI. More parts/humans = a stronger claim.
- **Editability (revision round) is representation, not magic:** a parametric build123d program
  absorbs a dimensional change by editing one constant; an exported STEP dumb-solid doesn't.
  That's a real productivity property of code-CAD, reported as exactly that.

## Environment (for byte-reproducibility)
<!-- AUTO: paste `pip freeze | grep -E 'build123d|cadquery|trimesh|scipy|numpy'` -->
Python 3.13.x (build123d 0.10 requires < 3.14). Tessellation tolerance pinned at 0.05 across
GT / human / AI. IoU is seeded + deterministic-voxel (`RewardConfig.seed=0`).
