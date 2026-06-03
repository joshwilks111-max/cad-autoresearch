# Design: skill decomposition (break the worker into per-axis skills?)

**Status:** DESIGN — reviewed, build starting rung-by-rung. Authored 2026-06-04 via `/autoplan`
(CEO + Eng + DX, Codex `gpt-5.5` + independent Claude subagents; 10 findings, 3 critical). The
interactive companion is `build-specs/DESIGN_skill_decomposition.html` (hover-gloss + believer/skeptic
toggle + ladder stepper); this `.md` is the canonical source.

**One-line:** the skill-based design the owner's intuition reached for *already exists in the repo*
(`skills/` — three MECE packs + a resolver) but was **never wired into the loop**, so every score on the
board came from the monolithic `program.md` worker — the hypothesis has not actually been tested. The
honest answer is a **scoped yes**, built as a six-rung ladder you can step off the moment a rung stops
beating the current worker.

---

## 1 · What's being asked

The worker is an AI agent that writes a small `build123d` program to rebuild a hidden target part. It
gets a composite score ∈ [0,1], a per-axis hint about what's wrong, and tries again — a tight
propose → score → revise loop (`run_inner_loop.py`). `≥0.95` composite = "solved".

Today that worker follows **one big instruction file** — `program.md` (213 lines), spawned as a single
`claude -p` call told "Read ./program.md and follow it exactly" (`loop/policies.py:107-150`). The
intuition under test: *a generalist following one broad manual hits a generalist's ceiling — so break it
into specialists, each expert at one axis of difficulty, with a smart coordinator picking which to use.*

**The reframe that changes everything.** A first cut of exactly this already sits in the repo:
`skills/drawing-read`, `skills/cad-reconstruct`, `skills/cad-grade` (each a `SKILL.md` + `evals/`) plus
`skills/RESOLVER.md` (the dispatcher table). BUT a Grep of the loop confirms it is **never loaded**:
`loop/policies.py` has ZERO references to `skills/`, `RESOLVER`, `--append-system-prompt`, or `--agents`,
and `program.md` never mentions them. A repo `skills/` dir does NOT auto-load into headless `claude -p`
(skills resolve via `/skill-name` or plugin/config registration; the loop does neither). **So the 13/13
solves and the floored hard parts ALL came from the monolith. The experiment has not run.**

There's also a mismatch. The shipped skills are cut by **pipeline stage** (read drawing → model → score).
The owner's intuition is about **axis of difficulty** (round vs prismatic, few faces vs many, one body vs
many). Different cuts. Tellingly, the hardest *stage* — drawing-read — is *already* its own skill and is
*still* at the field-wide vision wall (Opus ~40% vs Gemini ~77% dimension recall). So isolating a stage
did NOT lift that ceiling, because that ceiling is model eyesight, not organisation.

## 2 · The ceiling is two different numbers

"Hard parts cap around 0.8" hides the real story. Scores split into two regimes; decomposition only has
room to help in one.

- **Spec track: 13/13 solved ≥0.95.** When the dimensions are handed over, the generalist already nails
  it — the reward is monotonic with a steep gradient near the optimum (5/5 robustness probes refuted).
  **No headroom for decomposition here.**
- **Drawing / hard track: floored — but look WHERE.** `nist_ftc_09` (163 faces, 0.758), `nist_ctc_05`
  (156, 0.688), `nist_stc_06` (144, 0.628) sit just under a hard grader cap. `nist_ftc_07` (306 faces,
  ~0.24) and `nist_ctc_03` (120, ~0.17) are **featureless-box baselines** — never actually rebuilt, miles
  below even their cap.

**The key distinction.** "The ceiling" conflates the **grader cap** (≈0.88 for a 156-face part — unmovable
by any instruction, because a reconstruction from a few big shapes can never match a part *defined* by 156
little faces; a revolve gives ~57 faces → topology 0.286) with the **achieved score** (0.17–0.69). The
*gap between them* is the only room decomposition can win. On the empty-box parts that gap is ~0.7 (large);
on the spec parts it's zero (already at the top).

## 3 · The axes of difficulty

Studying the floored parts, difficulty isn't one thing — it's a small set that sorts cleanly into
**worker-addressable** (a better instruction can fix) vs **grader-structural** (only a human changing the
reward can fix).

| Axis of difficulty | Who can fix it | The tell-tale signal | Room |
|---|---|---|---|
| Reading the drawing | **worker** | dimensions read off the print (40% worker vs 77% tool) | high |
| Missing features (completeness) | **worker** | volume-overlap + volume error drop with missing material | high |
| Geometry build crashes | **worker** | did a solid build at all? + how much it shrank | med |
| Wrong build strategy | **worker** | overlap stuck while volume is fixable; seam-vs-missing face split | med |
| Face-count / topology | grader | 156 faces caps ~0.88 even when geometry is perfect | none |
| Internal hollow voids | grader | can't be seen from outside — unreconstructable | none |
| Round-part scoring noise | grader | score flips 1.00↔0.00 by triangle count (issue #7) | none |

The four worker-addressable axes are where a skill could earn its place. The three grader-structural ones
are walls — no prompt moves them. **Do NOT build a "topology skill":** it would be a confident-sounding fix
that mathematically cannot work.

## 4 · Does decomposition lift the ceiling? Both sides.

**Skeptic — it reorganises the same failure.** Three of the five floored parts are at their grader cap; no
better-organised agent can score materially higher (the math forbids it). The loop optimises a *single
composite* — add many skills and you add many chances for a **negative-transfer skill** you can't even
detect (SkillLens: ~25% of skill transfers are net-negative, and textual plausibility predicts utility
*worse than chance*). And a *cheaper* specialist model reads fewer dimensions — weaker on the one thing
that's hard. Higher-leverage instead: fix the round-part glitch, get a better drawing-reading *tool*, add
simple real parts. None of those is "reorganise the prompt."

**Believer — attribution makes it climbable.** The generalist leaves *measurable* room on the table: a
77%-accurate drawing reader sits unused behind the worker's own ~40% reading; the empty-box parts were
never rebuilt. Each axis owns a *different, clean* signal — and the reward was *already shaped* so that on
busy parts the volume-IoU is the sensitive layer (`reward.py` adaptive_feature_weighting shifts weight INTO
IoU for feature-rich parts, keyed on the hidden face count so it can't be gamed). So you gate each skill on
*its* signal, not the flat total. Honest scope: this wins on the drawing parts and the empty-box parts; it
does NOT move the capped parts (the believer concedes that ground).

**What decides it:** both cases collapse to one testable question — *does splitting the work and routing
beat just iterating with the current worker, at equal cost?* That's answerable cheaply (the ladder).

## 5 · What to build — a ladder you can step off

Not one big build. Each rung is cheap and sheddable. **Stop at the first rung that doesn't beat the current
worker.**

| Rung | Builds | Don't touch | Pass-gate |
|---|---|---|---|
| **0 · measure** | locked held-out set + a `turns-to-solve` scorer | grader, geometry kernel | scorer reads a saved run + reports the first attempt over the bar |
| **1 · point at tool** | one-line edit telling the worker the 77% drawing-reader exists + a one-off oracle test | the grading step | feeding the better reading lifts score ≥0.10 on a drawing part |
| **1.5 · smarter prompt** | ~10 lines: name the four failure-types the feedback already emits + the tactic for each | any loop code (manual only) | the feedback-aware worker beats the plain worker on the held-out set |
| **2 · rules** | a reader over the saved per-attempt detail + simple if-then rules | the grading call | rule-routing beats just-iterating on 2–3 known-hard parts |
| **3 · the router** | routing as a MODE of the worker-spawner (not a new kind — that forces a CLI edit) | the grading call (genuinely untouched) | routed worker solves held-out parts in fewer turns, at no higher cost |
| **4 · learning** | replace fixed rules with a bandit that learns which axis pays off | everything guarded | only IF rung 3 won AND there's stable data to learn from |

**The decisive finding from the review:** the worker *already* gets a per-axis "what's wrong" hint every
turn — `harness/feedback.py:hints()` (`:17-73`) already names the failure types (SOLID COLLAPSED, volume
OVER/UNDER, topology diff, low-IoU) and is already injected at `policies.py:124`. So **Rung 1.5 — a ~10-line
smarter prompt — probably captures most of the value with no router at all.** The full router only earns its
keep if a fixed/learned chooser beats a smart agent choosing for itself; its one irreducible advantage over
1.5 is switching the MODEL per axis (cost saving — only the tiebreaker). It may never be worth building.

**Do first / alongside (the parallel track).** Fix the round-part IoU glitch ([issue #7](https://github.com/joshwilks111-max/cad-autoresearch/issues/7);
the tolerant-dilation fix verified 0.78→0.93 but is NOT applied — touches guarded `geometry.py`, own
session) and add a few simple real parts. This lifts results decomposition *cannot* touch AND doubles as the
clean held-out set Rung 0 needs. Both strategy reviewers rated this higher-leverage than the skill work.

## 6 · Credit assignment — which skill gets the credit?

With many skills, a single total can't say which moved the score. The substrate is mostly already there.

Each axis owns a different signal:

| axis | signal |
|---|---|
| reading the drawing | dimension-recall accuracy — *off-total, measured before any building* (and only offline) |
| missing features | volume-overlap + volume error — the only layers that drop with missing material |
| geometry crashes | did a solid build at all? + how much it shrank — independent of everything else |
| wrong strategy | overlap stuck while volume is fixable; the seam-vs-missing split in the face count |

`reward.py` already returns a detailed `raw[]` breakdown (`topology_exact`, `volume_rel_err`,
`bbox_worst_axis_err`, `weights`, …) and it is **already persisted on every ledger row** (`breakdown.raw`,
written `run_inner_loop.py:177-181`). The fix is NOT new plumbing — it's a small **reader** over that saved
detail. **The honest limit:** on a capped part the total is *flat* — so the skill there must gate on an
*off-total* signal (reading accuracy, missing-material, build-success), never the total. That is exactly the
"gate on the real failure mechanism, not on how plausible it sounds" rule from the skill literature.

## 7 · Load-bearing invariants (do NOT violate — these are why the design is safe)

1. **The grader is untouchable.** Never edit `harness/`, `reward.py`, `geometry.py`, the orchestrator's
   grading path, or any `ground_truth/`. Only a human changes the reward (`CLAUDE.md` guardrails). Every
   rung below the router is *additive + offline*; the router is a MODE of the proposer, NOT a new grading
   path.
2. **The real metric is autonomy, not a number nudge.** The top-line is "did it rebuild a part
   start-to-finish with no human," measured as **turns-to-solve on a LOCKED held-out part** — not "did a
   tweak move a score-delta on a part we already know is hard" (that's tuning on the answer). Per-axis
   sub-scores are demoted to diagnostics.
3. **Round-symmetric parts are excluded from any before/after gate.** Round-part IoU is nondeterministic
   (`geometry.py` radial-frame quantization, issue #7). A gate that includes them measures noise. Mark them
   as a task field (`rotational_symmetry`), never a hand-kept list (which silently drifts).
4. **Billing stays on subscription.** `claude -p` bills the subscription via OAuth; keep
   `ANTHROPIC_API_KEY` unset (if set, the CLI prefers it and silently bills the metered API — the opposite
   of intended). The loop scrubs it at the spawn seams (`loop/billing.py`).

## 8 · What the review gauntlet caught (all fixed)

The first draft kept *overstating how clean the idea was*. The corrections, verified against source, WILL
RECUR — they are written here so the next session doesn't re-make them:

1. **The first "gate" was circular** — "run the make-or-break test before building the router," but the test
   needs the router. → Replaced with the 6-rung ladder, each rung gating the next.
2. **It optimised a stand-in** — score-deltas on known-hard parts = tuning on the answer. → Top metric is now
   turns-to-solve on a LOCKED held-out part.
3. **"Zero code changes" was overstated** — `run_inner_loop.py:116` hard-codes `--proposer
   choices=["mock","claude"]`, so a "router" type needs a CLI edit. → Routing is a MODE of `ClaudeCodeProposer`,
   no new type; the grading path is genuinely untouched. (Corrected claim: "zero edits to the GRADING path,"
   not "zero edits.")
4. **The drawing-accuracy score isn't a live signal** — `evals/drawing_read_eval.py` is OFFLINE-only (pure
   dict-in/out, fixture key, `RUN_LLM_EVALS=1`, tests-only). → Demoted to an offline diagnostic; the live
   vision signal is just "did the dimensions come out right."
5. **The data path was wrong** — the workspace is `run_dir/{worker}/attempt_NNN`, three levels below the
   ledger, and no key names it. → Hand the per-attempt `raw[]` to the worker in-memory (enrich `history`,
   one line at `run_inner_loop.py:192-193`), not by re-reading a file.
6. **It would crash on the common case** — a body-gate failure returns `raw` with ONLY
   `candidate_watertight` (`reward.py:196-203`); a reader expecting full detail crashes on every failed
   attempt, and early attempts fail a lot. → The reader `.get`s everything + treats body-failure as its own
   robustness state. (`vc_vg` is DERIVED, not a raw key.)
7. **Vision could loop forever with no API key** — `drawing_extract.py` is metered Google HTTPS
   (`~/.banana/api_key`), scaffold-on-failure; a blank read as "low accuracy" retries forever. → Gate +
   cache it; "vision unavailable" is a distinct state.
8. **The full router is over-built** — the per-axis hint already exists + is already injected. → Added Rung
   1.5; the router must now beat the *smarter prompt*, not the plain worker.
9. **The round-part exclusion was a maintenance trap** — a hand-kept list in loop code duplicates a fact in
   the geometry kernel. → A field on each task; the parallel-track fix removes the need entirely.
10. **As a doc to act on, it buried the lede** — a fresh reader couldn't tell what to do first or how to know
    a step worked. → Added the Quickstart + glossary (the `.html` companion is part of this fix).

The strategy and architecture reviewers independently reached the same verdict: **the idea is sound, the
architecture is over-built — build the cheap rungs and let evidence decide the rest.** The core thesis
survived; the engineering honesty got fixed.

## 9 · Verdict & the seven questions

1. **What are the axes?** Four worker-fixable (reading, completeness, robustness, strategy) + three
   grader-walls (face-count, hollow voids, round-part noise). §3.
2. **Does it lift the ceiling?** Yes on the worker-fixable parts; no on the capped ones. The gap from
   achieved-score to grader-cap is the prize. §2, §4.
3. **The architecture.** A routing *mode* of the existing proposer — reads the per-axis breakdown, picks a
   skill prompt + model (cheap models for skills, smart model as chooser). §5.
4. **Credit assignment.** Each axis owns its own signal; the breakdown is already saved; a small reader
   exposes it. Capped axes gate off-total. §6.
5. **Search philosophy.** Parallel cheap probes + a chooser, not assumed steady progress ("100 shots; take
   the one that hits"). A learned chooser only after fixed rules win. §5 rungs 2–4.
6. **Is the gate higher?** Yes — "did it rebuild a part start-to-finish with no human," as turns-to-solve on
   a held-out part. Not "did a tweak nudge a number." §7.
7. **Where does vision fit?** A tool the worker *can* reach for, never a forced step. Point it at the 77%
   reader; let the loop learn when to use it. But it's a metered, networked call — gate and cache it. §8.

**Recommendation.** Scoped yes, resized down by the review. Run the parts-and-glitch parallel track *first*
(it lifts what decomposition can't, and feeds it). Build the measurement step (Rung 0), the one-line tool
pointer (Rung 1), and the ~10-line smarter prompt (Rung 1.5) — and let *that* evidence decide whether the
full router ever gets written. **Don't build a topology skill. Don't build the learned chooser until fixed
rules have already won.**

## Prior art (verified, not stale memory)

- **SkillLens** (microsoft.github.io/SkillLens) — skill utility = concrete failure-mechanism encoding, NOT
  textual plausibility; ~25% negative transfer. The source of the "gate on the real mechanism" rule.
- **SkillOpt** (arXiv 2605.23904) — validation-gate on a held-out set.
- **arXiv 2601.04748** — "When Single-Agent with Skills Replace Multi-Agent Systems" (the Rung-1.5-beats-router
  thesis in the literature).
- Existing CAD multi-agent systems (LL3M arXiv 2508.08228, "Idea to CAD" 2503.04417, CADDesigner 2508.01031)
  all use **role** decomposition (Analysis/Geometry/Validation agents), NOT axis-of-complexity decomposition
  — the owner's framing is novel.

## References

- `docs/designs/metric-authoring-skill.md` — the sibling design (same Software-3.0 inversion, aimed at the
  *grader* instead of the *worker*). The grader has a clean property-based eval to gate quality; a worker
  skill's only trustworthy gate is the composite reward, which is flat-capped on the hard parts.
- `docs/known-limitations.md` — the topology cap (§), round-part IoU (§2), determinism (§9).
- `docs/research-and-deferred.md` — roadmap; add a forward pointer here.
- `LEADERBOARD.md` — the two-regime data this design rests on.
- [issue #7](https://github.com/joshwilks111-max/cad-autoresearch/issues/7) — the round-part IoU
  nondeterminism that scopes the exclusion + motivates the parallel track.
- Build state (2026-06-04): Rung 0 (`evals/turns_to_solve.py` + manifest `holdout`/`rotational_symmetry`
  fields) and Rung 1.5 (`program.md` feedback-aware section) are the first rungs built against this design.
