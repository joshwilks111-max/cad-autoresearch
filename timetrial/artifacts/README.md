# Trial artifacts

Committed evidence so a skeptic can re-grade the result without trusting `RESULTS.md`.
Populated when the timed run happens (per `../PROTOCOL.md`). Expected contents:

- `human_build.step`, `ai_build.step` — the build-round submissions (real B-rep solids).
- `human_revision.step`, `ai_revision.step` — the revision-round submissions.
- `ai_build_candidate.py` — the build123d program the AI's build-round STEP came from
  (shows the revision was a one-constant edit).
- `results.jsonl` (copied from `..`) — the recorded turns/seconds/scores.
- `SHA256SUMS` — hashes of every STEP above, so the graded artifacts are tamper-evident.

Re-grade any of them:
```
python ../grade_step.py --task trial_lbracket --step human_build.step
```
Or open the `.step` files in any CAD viewer and compare to `../../tasks/trial_lbracket/drawing.png`.
