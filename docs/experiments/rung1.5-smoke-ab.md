# Experiment: Rung 1.5 Smoke A/B — feedback-aware `program.md`

**Status:** RUN — smoke check complete 2026-06-04. n=2 floored hard parts, budget 6, spec track,
`claude -p` (subscription/OAuth). NOT the full held-out verdict.

**One-line:** naming `harness/feedback.py`'s verbatim hint strings in `program.md` (the Rung 1.5
category→tactic table) did **not** lift best-score on two floored hard NIST parts — direction is
flat-to-negative, which is the pre-registered "Opus already decodes these hints" outcome.

## What was tested

Does the **feedback-aware `program.md`** (AFTER: 232 lines, `main`/`1714fd7`) beat the **plain
pre-1.5 `program.md`** (BEFORE: 213 lines, `45f51e4`) on two non-symmetric floored parts?

The treatment is a single contiguous edit — `git diff 45f51e4 1714fd7 -- program.md` — a 7-row
category→tactic table inserted between "the lowest sub-score is your target" and "Spawning
subagents." Each row maps one **verbatim** `feedback.py::hints()` string (`SOLID COLLAPSED`,
`Volume is X% OVER`, `Topology differs`, `Low volumetric IoU`, …) to a specific fix. Same feedback
signal is injected either way (`loop/policies.py` `FEEDBACK FROM YOUR LAST ATTEMPT` block); Rung 1.5
only changes how the worker is told to *interpret* it. One variable, no grading-path change.

The swap-the-file mechanic is valid because the worker reads `program.md` **fresh from disk every
spawn** (`loop/policies.py`: prompt = "Read ./program.md and follow it exactly", `cwd=repo_dir`,
file not inlined). The file on disk at spawn time *is* the condition. AFTER ran with the file at
232 lines; the working tree was then transiently swapped to the 213-line version (`git show
45f51e4:program.md > program.md`, HEAD untouched) for the BEFORE arm, then restored
(`git checkout program.md`). The committed diff is this doc only — `program.md` is unchanged at HEAD.

## Parts (both `holdout: true`, both NOT `rotational_symmetry`)

- **`nist_ctc_03`** — 120 faces, euler=95, bbox ~320×534×163, tier medium. Floored well below the bar.
- **`nist_ftc_07`** — 306 faces, 3 shells (euler=0, "adversarial topology probe"), bbox ~352×136×263,
  tier hard. Topology-capped.

Both are voxel-IoU-path parts (not the nondeterministic cylindrical/round-part path, issue #7), so
the grader is deterministic and any best-score delta is signal, not IoU jitter. Both are
`default_track: drawing` but have **no `drawing.png` asset** on disk, so the A/B ran on `--track spec`
— a valid proxy for the prompt-comprehension delta (high face count makes them hard on either track;
a true drawing-track A/B needs the assets sourced first — separate task).

## Results

Scored with `evals/turns_to_solve.py --json` (bar 0.95). `best` = max composite across all attempts
in the run-dir; turns-to-solve is `—` for every arm because neither part crosses 0.95 (expected —
these are floored parts, so **`best` is the primary signal**, turns-to-solve is informational).

| part        | before_best | after_best | delta (after−before) | before_turns | after_turns |
|-------------|-------------|------------|----------------------|--------------|-------------|
| nist_ctc_03 | 0.4938 †    | 0.4344     | **−0.0594**          | —            | —           |
| nist_ftc_07 | 0.6365      | 0.6271     | **−0.0094**          | —            | —           |

† **BEFORE/ctc_03 caveat:** attempts 1 and 4 hit `cli_timeout` (the `claude -p` spawn exceeded the
600s per-spawn cap and produced no code), so this arm reached 0.4938 on **4 scored turns, not 6**.
The AFTER arm had all 6. That the *fewer-turn* arm scored *higher* makes the "no help" read stronger,
not weaker — but it is a turn-count asymmetry, recorded here for honesty. All other arms: 6/6 turns,
every turn `cli_returncode=0`, `body=1.0` (watertight solid built) — no machinery failures.

**Per-arm shape (for context):**
- `ftc_07` clustered tightly in BOTH arms (BEFORE 0.624–0.636; AFTER 0.515–0.627) with `topo` pinned
  at ~0.11 every turn — a grader-structural topology cap (3 shells, euler=0) that no prompt can move.
  Volume/bbox/surface-IoU were near-perfect in both arms; the worker saturates fast against the cap.
- `ctc_03` hill-climbed raggedly in both arms (0.15–0.49 swings) on a rugged reward surface; both
  arms reached `vol=1.000 bbox=1.000` on their best turn but stalled on internal feature recall.

## Direction

**Flat-to-negative.** Neither part shows the feedback-aware table beating the plain prompt. `ftc_07`
is flat within noise (−0.009). `ctc_03` is −0.059 in favour of BEFORE, confounded by the 2 lost
BEFORE turns. No arm crosses the bar; turns-to-solve is undefined for all four.

## Read

On these two floored hard parts, naming `feedback.py`'s hint strings in `program.md` did not change
the worker's reached best-score. The most parsimonious explanation is the one the plan pre-registered:
**Opus already decodes the feedback hints** without an explicit category→tactic lookup — the generic
"fix the lowest sub-score" instruction in the BEFORE prompt is sufficient for it to infer the same
tactics the AFTER table spells out. The hardest part (`ftc_07`) is additionally pinned by a
topology cap that is grader-structural, so no prompt edit could move it regardless.

This is a SMOKE check (n=2 parts, budget 6, spec track) — direction-of-effect and machinery, not the
full held-out verdict. It does not refute the broader skill-decomposition design; it tests the
*cheapest* rung and finds it does not beat the monolith here. Per the plan's decision rule, a flat
result **deprioritises the router rungs (Rung 3 bandit-free, Rung 4 bandit)** — there is no evidence
the worker needs explicit hint-routing — and redirects attention to the actual bottleneck the design
doc names: the **drawing-read cap** (Opus ~40% vs Gemini ~77% dimension recall), which needs the
drawing assets sourced before it can be measured.

## Reproduce

```
# AFTER arm (program.md at 232 lines on disk):
python run_inner_loop.py --task nist_ctc_03 --proposer claude --model opus --budget 6 --track spec --run-dir runs/ab_after_ctc03
python run_inner_loop.py --task nist_ftc_07 --proposer claude --model opus --budget 6 --track spec --run-dir runs/ab_after_ftc07
# swap to BEFORE: git show 45f51e4:program.md > program.md   (213 lines, table gone; HEAD untouched)
python run_inner_loop.py --task nist_ctc_03 --proposer claude --model opus --budget 6 --track spec --run-dir runs/ab_before_ctc03
python run_inner_loop.py --task nist_ftc_07 --proposer claude --model opus --budget 6 --track spec --run-dir runs/ab_before_ftc07
# restore: git checkout program.md   (back to 232)
# score:
python evals/turns_to_solve.py --run-dir runs/ab_<arm>_<part> --json
```

Billing: `claude -p` bills the **subscription via OAuth**; `ANTHROPIC_API_KEY` kept unset (the loop
also scrubs it + `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` at each spawn, `loop/billing.py`). The
`runs/` copies are gitignored; this committed doc is the durable record.
