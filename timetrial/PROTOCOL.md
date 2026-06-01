# Time-Trial Protocol — human vs AI on one real part

The deliverable that answers Tim's *workflow* claim ("AI doesn't make a working engineer
2× faster") with a **measured** number, not an asserted one. A human and the AI loop each
model the SAME part from the SAME drawing, both graded by the SAME deterministic referee
until **verified-correct**; then both handle one **revision**. We report turns + wall-clock.

The machine-readable contract is `protocol.yaml` (pre-registered — fixed before any run).
This file is the human-readable procedure.

## What makes it honest (read before running)
1. **One referee, both sides.** Every submitted STEP is graded by `timetrial/grade_step.py`,
   which computes a **B-rep** topology signature (`import_step → topology_signature_from_solid`),
   NOT the mesh proxy. Without this a perfect human STEP would be pinned at topology=0.5 while
   the AI scores 1.0 — non-commensurable. (This is the bug the eng review caught; grade_step.py
   exists to avoid it. Self-test: grading the GT STEP prints ~1.0 / topo=1.000.)
2. **No oracle for the AI.** The normal `grade_one.py` feedback renders candidate-vs-GT and
   prints GT volume/bbox/topology deltas — an *answer key* the human doesn't get. During the
   trial the AI gets only **pass/fail + its own renders** (the same information the human has:
   the drawing + "is it right yet?"). Otherwise it's an oracle-assisted reconstruction race,
   not a productivity race.
3. **Neither competitor opens `ground_truth/`** (the STEP/STL/topology) or `spec.md` (drawing
   track derives geometry from `drawing.png` only).
4. **Primary metric = turns-to-verified** (deterministic). Wall-clock is secondary and is the
   **end-to-end** time (human stopwatch; AI = kickoff→verified-turn session time INCLUDING
   inference + operator latency). Do NOT sum `RunResult.seconds` — that's CAD-build time only,
   zero inference, and undercounts the AI by orders of magnitude.
5. **Same inputs, same done-bar:** both start from `drawing.png`; done = composite ≥
   `verified_correct_bar` (0.95) via grade_step.py.
6. **n=1, demonstration not production.** One part, one human, one AI run = an existence proof
   you can reproduce, NOT a statistical "2×". And the referee needs ground truth — in real work
   the engineer doesn't have the answer key, so this DEMONSTRATES the loop reaches a
   verifiable-correct part fast; verifying without GT is the deferred next step. Say so in
   RESULTS.md; overclaiming hands the skeptic the citation.

## Round 0 — pre-flight (done)
- Part: `trial_lbracket` (gusseted L-bracket, ~17 faces, prismatic, distinct 120/60/44 extents
  → voxel IoU path). GT built from forward-authored intent (license-clean). Drawing rendered.
- Confirm: `ls tasks/trial_lbracket/ground_truth/result.stl` and the part takes the VOXEL IoU
  path (it does — eigenvalue ratios 1 : 2.8 : 13).
- `python timetrial/grade_step.py --task trial_lbracket --step tasks/trial_lbracket/ground_truth/result.step`
  should print ~1.0 (referee self-test on this part).

## Round 1 + 2 — the build round (human, then AI)
Each competitor, independently, from `drawing.png` only:
1. Note `ts_start`.
2. Model the part. **Human:** in FreeCAD / build123d / their CAD; export a STEP.
   **AI:** the interactive Claude session runs the loop (write `candidate.py` → grade →
   read pass/fail + own render → fix), per `KICKOFF_PROMPT.md`, no-oracle feedback only.
3. Done when grade_step.py reports composite ≥ 0.95. Note `ts_end`, count turns.
4. Record:
   ```
   python timetrial/trial.py record --competitor <human|ai> --round build \
       --task trial_lbracket --step <their.step> --turns <N> --seconds <ts_end-ts_start> \
       --ts-start <ts_start>
   ```

## Round 3 — the revision (editability — the real productivity bottleneck)
The pre-registered change (`protocol.yaml`): **base bolt-hole X-spacing 90 → 98 mm**.
- Build the revised GT once: a `trial_lbracket_rev` task (the L-bracket with that one dim
  changed), so both sides are graded against the corrected part.
- Issue the SAME change to both. **AI:** edit the one constant in `candidate.py`, re-run.
  **Human:** edit their model / re-model as their representation requires.
- Record both with `--round revision`.
- HONEST framing (eng review): this measures "does the competitor's representation absorb a
  dimensional change cheaply?" A parametric build123d program changes one number; an exported
  STEP dumb-solid does not. Report it as *that*, not as a generic "human can't edit."

## Results
```
python timetrial/trial.py aggregate     # table + computed headline -> results_table.md
python timetrial/trial.py verify --bar 0.95   # re-grade all STEPs from disk + honesty checks
```
Then assemble `RESULTS.md` (objection-first; lead with turns-to-verified; embed the table,
the drawing, both STEPs' hashes; invite the reader to open the STEPs in any CAD viewer).
