# Why the reward is shaped this way

The design rationale behind `harness/reward.py`. The mechanics (layers, weights, functions) are
in [ARCHITECTURE.md](ARCHITECTURE.md); this explains the *decisions* — why seven independent
layers, why these weights, why adaptive weighting exists, and what each choice traded away. Read
this before changing the reward; most of the non-obvious structure is load-bearing.

---

## The problem the reward solves

An AI writes a build123d program to reconstruct a hidden ground-truth part. We need ONE scalar in
[0,1] that says "how close is this?" — and it has to be **honest about partial credit** and
**impossible to game**. A single metric can't do this: a candidate can nail the bounding box while
getting the topology completely wrong, and the score must reflect that split, not average it into a
misleading middle.

The deepest design constraint: the score is what the agent climbs. **A reward with no gradient where
the geometry is wrong is useless** — the agent gets stuck. So every layer is judged not just on "is
it correct" but on "does it produce a usable gradient as the candidate approaches correct."

## Why seven independent layers, not one composite metric

Each layer measures a different *kind* of wrongness and they fail independently:

- **body** (gate) — did we get a non-empty solid at all? Forces composite ≈ 0 on empty/fragment
  results no matter what the other layers say. Without this, a garbage solid that happens to have a
  plausible bbox scores partial credit.
- **volume** — total material. Catches "too much / too little stuff."
- **bbox** — overall size/proportion on the worst sorted axis. Catches "right volume, wrong shape."
- **topology** — B-rep feature count. Catches "right shape, missing holes/features."
- **iou** (volumetric) — where the material actually IS in space. Catches "right volume + bbox but
  in the wrong places."
- **chamfer** — surface distance. Catches fine surface-shape error.
- **siou** (surface IoU) — surface-shape agreement, complementary to volumetric IoU.

Keeping them separate means the **feedback** can tell the agent exactly which axis failed ("volume
+14%, topology 0.29") instead of a single opaque number. That's the difference between an agent that
self-corrects and one that flails.

## Why these weights (iou 0.25 > vol 0.20 = cham 0.20 > bbox 0.15 = topo 0.15 > siou 0.10)

The weights encode **which layers carry the most signal about real reconstruction quality**:

- **IoU is the heaviest (0.25)** because it's the only layer that tracks *missing material
  proportionally* — a missing hole drops IoU ~in proportion to the hole's volume. It's the most
  honest "are the right things in the right places" signal.
- **Volume and Chamfer (0.20 each)** are strong but coarser — volume is a single scalar (a part can
  have correct total volume with material in the wrong place), Chamfer is surface-only.
- **bbox and topology (0.15)** are important but each is "binary-ish": bbox is nearly satisfied or
  not; topology is a count match that's either close or not.
- **SIoU is lightest (0.10)** — it was added (funded by reducing IoU from 0.30) to catch surface-shape
  errors that volume-identical solids mask (a flat face where a curved one belongs), but it's
  structurally blind to small-fraction errors, so it earns the smallest base weight.

These are tuned values, not first principles — if you change them, re-run the leaderboard and confirm
no solved part regresses (the `test_reward.py` suite + the per-part `.best_score` values are the
guard).

## Why adaptive feature-weighting exists (the most subtle piece)

**The measured problem (WF-M, 2026-05-30):** on a feature-rich part (many small holes/pockets),
volumetric IoU is the ONLY layer sensitive to missing material — a 7%-volume hole field shifts
Chamfer and Surface-IoU *less than their sampling floor*, so they're effectively blind to it. The
consequence: a hole-LESS box scored high on the surface terms against a holed GT, because the surface
layers couldn't see the missing holes.

**The fix:** as the GROUND TRUTH's B-rep face count rises (more features = more small-fraction error
the surface layers miss), shift weight OUT of the blind layers (chamfer, siou) INTO the sensitive ones
(iou, topology). Mechanically (`_adaptive_weights`): `richness` ramps 0→1 over [`afw_face_lo`=15,
`afw_face_hi`=120] GT faces; at full richness `afw_max_shift`=0.10 of weight moves, 70% to iou
(`afw_iou_share`) and 30% to topology.

**Why it's keyed on the GT, not the candidate:** if it were keyed on the candidate's face count, a
proposer could game it by adding faces to shift the weighting in its favor. Keying on the hidden GT's
face count makes it **ungameable** — the agent can't see or influence it.

**Trade-off:** it makes the scores of complex parts depend on a GT property the agent can't observe,
which is fine for grading but means you can't compare a 15-face part's composite directly against a
156-face part's composite — they're scored on different weight mixes. (That's correct: they're
different difficulty regimes. See the topology ceiling in [known-limitations.md](known-limitations.md#1).)

## Why tolerance ramps, not hard thresholds

Volume / bbox / chamfer use a linear ramp: full credit at ≤ `soft` error, zero at ≥ `hard`, linear
between (`_ramp`). A hard pass/fail threshold gives the agent no gradient to climb toward — it's
either 0 or 1 with nothing in between. The ramp means every percent of improvement shows up in the
score, which is what lets the loop converge. The `soft`/`hard` bands (e.g. vol 1%/25%) are set so that
"essentially correct" gets full credit and "wildly wrong" gets zero, with a usable slope between.

## Why IoU sampling is so heavy (and adaptive)

IoU needs FAR more points than Chamfer to stay self-consistent run-to-run (60,000 interior samples vs
8,000 surface samples; a dense voxel grid). A sparse IoU is noisy — the same candidate scores
differently on re-run, which poisons the loop. The grid resolution is **adaptive** (`iou_target_pitch_mm`
= 1.25mm, res = `clamp(max_extent/1.25, 24, 64)`) because a flat-64 grid is wasteful on small parts and
too coarse on large ones; the per-part pitch registers a ~1mm feature shift without paying flat-64 cost
everywhere. This fixed the small-feature gradient gap (see [known-limitations.md](known-limitations.md#6)).

## The unifying weakness (worth internalizing)

Several limitations trace to one root: **the reward under-weights small-FRACTION errors.** A missing
hole, a slightly-wrong count, a small displaced feature — each is a tiny fraction of the total
volume/area/face-count, so most layers barely move. IoU + topology are the only layers that track them,
which is exactly why adaptive weighting funnels weight there for feature-rich parts. If you're designing
a new layer or fix, ask: *does it give signal on small-fraction errors?* That's the axis the reward is
weakest on, and the one most worth strengthening. The deferred surface-histogram topology layer is the
next move on this axis (see [research-and-deferred.md](research-and-deferred.md)).

## What NOT to change without care

- The **body gate** (composite = body × weighted_sum). Removing it lets fragment solids score partial
  credit — the OCC silent-boolean trap (limitations #3) becomes a scoring hole.
- **Determinism** — fixed seed, RNG-free voxel centers, restored global RNG. A non-deterministic grader
  is unusable for the loop (limitations #8).
- **Keying adaptive weighting on the GT.** Switch it to the candidate and it becomes gameable.
- The **weights**, without re-running the leaderboard. They're tuned; a change that helps one part can
  regress a solved one.
