# Design: metric-authoring skill (Software 3.0 for the grader)

**Status:** DESIGN ONLY — not built. Authored 2026-06-03 from a `/plan-ceo-review` (SELECTIVE
EXPANSION) + Codex outside voice. Build is a dedicated future session, gated on its own scope review.

**One-line:** make authoring the grader's deterministic geometry kernels a *skill* (prompt + an
accumulating eval benchmark) instead of a human hand-patching `harness/geometry.py` at 11pm — so the
*next* round-part-IoU-class bug is cheap to fix and the benchmark becomes durable institutional memory.

---

## Why (the motivating pattern)

This harness's whole thesis is Software 3.0: you specify INTENT in natural language (`program.md`,
`spec.md`) and a deterministic eval (`reward.py`) closes the loop — the human iterates the *prompt*, not
the implementation. The ONE place the project reverted to Software 1.0 is the grader's geometry kernels:
`harness/geometry.py` (`_cylindrical_iou`, `iou`, `surface_iou`) is hand-written numerical code.

That code has now been fixed **twice** for round parts and is *still* partial:
- commit `9dcded5` — rotation-invariant cylindrical IoU + axial-sign search (FTC-11 0.619→0.986);
- 2026-06-03 — a DIFFERENT degeneracy reproduced (`bearing_608` flips iou 1.00↔0.00 by tessellation;
  see [issue #7](https://github.com/joshwilks111-max/cad-autoresearch/issues/7), `known-limitations.md` §2).

A function fixed twice and still leaking is telling you the **abstraction** is wrong, not that you keep
missing a case. The 10x move: stop hand-patching kernels. Let an eval-gated skill GENERATE the kernel, and
let an accumulating benchmark of every degeneracy ever hit be the source of truth.

## What it is

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │  metric-authoring SKILL  =  PROMPT  +  PROPERTY-BASED EVAL BENCHMARK  │
  └─────────────────────────────────────────────────────────────────────┘
         │                                              │
         │ 1. LLM reads the benchmark + the metric spec │
         │    and GENERATES a candidate kernel          │
         ▼                                              │
   ┌──────────────┐   fails some cases   ┌──────────────┴───────────┐
   │ candidate    │ ───────────────────► │ iterate the PROMPT        │
   │ kernel (.py) │ ◄─────────────────── │ (not the code by hand)    │
   └──────┬───────┘   regenerate         └───────────────────────────┘
          │ passes ALL benchmark invariants
          ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  FREEZE: verify byte-deterministic, human reviews, commit into     │
   │  harness/geometry.py  (guarded — human approves the merge)         │
   └──────────────────────────────────────────────────────────────────┘
          │
          ▼
   runtime grader runs the FROZEN python.  LLM is GONE.  No model at grade time.
```

The benchmark accumulates every degeneracy as a permanent regression case (the joint-grid angular flip,
the axial-sign flip, the FTC-11 false-low, the stepped-part false-positive). **The code becomes a
disposable build artifact; the benchmark becomes the durable asset.** That inversion — spec+eval is the
source of truth, implementation is regenerable — is the Software-3.0 core.

## Load-bearing invariants (do NOT violate — these are why the design is safe)

1. **The LLM authors OFFLINE and never runs at grade time.** The reward must be deterministic — a grader
   that scores the same candidate differently on re-run is unusable as a gradient (`known-limitations.md`
   §9, lines 184-190). The skill produces *frozen python*; the runtime grader imports that python and
   calls no model. An "LLM judges geometry similarity at grade time" design is REJECTED — it breaks the
   one invariant the loop depends on.
2. **Determinism is verified before freeze.** The generated kernel is run twice on the benchmark and must
   be byte-identical. Tessellation tolerance stays pinned (harness uses 0.05 throughout, `:189-190`). No
   version-dependent dependency (e.g. a `scipy.ndimage` default structuring element) enters the hot path
   without an explicit determinism pin.
3. **Guarded-code boundary: the skill PROPOSES, a human FREEZES.** `harness/geometry.py` is guarded
   (`CLAUDE.md`). The skill outputs a candidate kernel + the eval evidence; a human reviews and approves
   the merge — the SAME gate as any guarded change. This is explicitly **NOT** "the loop edits its own
   grader." The autonomy is in *drafting*, never in *landing*.

## The benchmark MUST be property-based, not case-based (Codex's structural warning)

This is the single most important design constraint, and the reason a naive version is dangerous.

**The grader IS the optimization target.** The agents optimize their CAD against whatever the kernel
scores. So a benchmark-overfit kernel doesn't just mislead the *author* — it actively *trains the agents
toward wrong geometry* while passing every historical case and showing green the whole time. A finite set
of "these N parts score right" (case-based) can encode yesterday's bugs and miss tomorrow's geometry.

The defense: assert **invariants** (properties that must hold for ALL inputs of a kind), including
**adversarial false-positive** cases (parts that are WRONG but might score high):

- rigid-transform invariance (translate/rotate a solid → score unchanged);
- same-solid-different-construction equivalence (the issue-#7 case: two builds of one solid agree);
- STEP/STL round-trip + tessellation-perturbation stability;
- candidate vertex-order invariance;
- monotonic penalty for feature shifts / removals (a bigger error scores lower);
- deterministic repeatability (re-run → identical);
- **adversarial false-positive resistance** — stepped-hub vs straight bushing with matched support,
  cone vs cylinder, wrong flange-z → all MUST score clearly low. (This is exactly the failure the
  rejected 1-D-marginal fix would have introduced; the benchmark must make it impossible to pass a kernel
  that has it.)

The property-based benchmark built in the round-part-IoU fix (`tasks/iou_benchmark/`) is the seed of this
asset — the skill consumes the same benchmark, just iterating a generated kernel against it instead of a
hand-written one.

## Open questions for the build session

- **Kernel surface:** which functions are in-scope for generation? Start with `_cylindrical_iou` only
  (proven need), or the whole `geometry.py` IoU/SIoU family?
- **Freeze mechanics:** how is "byte-deterministic" verified in CI — a repeat-run hash gate?
- **Prompt iteration loop:** human-in-the-loop each round, or a bounded auto-loop that stops on
  all-green-then-surfaces-for-approval?
- **Benchmark growth:** how does a newly-discovered degeneracy get added as a property without
  over-fitting to that one part?

## Explicitly NOT this design

- LLM in the grade-time scoring path (breaks determinism).
- The skill auto-committing to `harness/geometry.py` (violates the guarded-code boundary).
- A purely case-based benchmark (overfit trap — the grader is the optimization target).

## References

- `docs/known-limitations.md` §2 (round-part IoU) + §9 (determinism) — the constraints.
- `docs/research-and-deferred.md` — roadmap entry pointing here.
- [issue #7](https://github.com/joshwilks111-max/cad-autoresearch/issues/7) — the bug that motivated the bet.
- `tasks/iou_benchmark/` — the property-based benchmark seed (built with the round-part fix).
- The gbrain concept `templates-are-priors-eval-is-the-closed-loop` — the prior-art pattern this applies.
