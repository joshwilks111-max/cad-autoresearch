# Research log & deferred work

What's been **solved**, what's been **tried and rejected** (so you don't redo it), and what's
**deferred** (the roadmap, ranked). This is the project's institutional memory — read it before
starting a new improvement so you build on what's known instead of rediscovering it.

Explanation doc. See also [known-limitations.md](known-limitations.md) (the traps),
[ARCHITECTURE.md](ARCHITECTURE.md) (the mechanics), `LEADERBOARD.md` (current per-part scores).

---

## Solved (don't re-litigate these)

- **The reward is at benchmark parity.** Seven independent layers (body/volume/bbox/topology/
  iou/chamfer/siou) after Reshef Elisha's Onshape eval rubric. P0 hardening done + verified:
  deterministic IoU, Euler-χ in the topology signature, RNG restoration. The geometric reward is
  sound and robust; the frontier is breadth + the *engineering-correctness* and *authoring-feedback*
  axes, not the core geometry score.
- **Round-part cylindrical IoU (PARTIAL — a real bug remains, confirmed 2026-06-03).** Rotation-
  invariant radius×axial occupancy fixed the false-low IoU on high-aspect annular parts (FTC-11 + 3
  synthetic round parts). **Still broken — radial-frame quantization:** two equal round annuli built
  different ways (`Circle` vs `Ellipse(11,11)`) tessellate differently and score `iou=0.7826` through
  the real grader (reproduced in `scripts/iou_roundpart_diag.py`, issue #7). Root cause = the sampled
  shared `rmax` at `geometry.py:259`; a sub-micron `r.max()` delta shifts all radial bins (axis is
  stable — NOT an angular/axis bug). Fix = tolerant joint (r,z) comparison (numpy ±1-bin dilation,
  verified to recover 0.78→0.93); NOT 1-D marginals (they false-positive on stepped parts). Guarded —
  needs approval. See the deferred entry below + limitations #2.
- **Reward-honesty fixes.** (a) topology schema-mismatch returns neutral 0.5 instead of 0.0 when a
  mesh-proxy signature meets a B-rep GT signature (they share only euler, with different defs).
  (b) Adaptive feature-weighting (shift weight into iou+topology for feature-rich GTs, keyed on GT
  face count so it's ungameable). Both audited ungameable + zero-regression.
- **Small-feature gradient.** Adaptive IoU pitch (1.25mm target) — a 1mm rib shift now registers
  (0.992 → 0.900). See limitations #6.
- **Two solved real parts:** bearing_608 (0.997) and FTC-11 washer (0.956). The pattern for adding
  more: find a <~15-face real STEP, rebuild the GT from its public standard dimensions in a
  `make_ground_truth.py` (license-clean — never commit a third-party STEP), reconstruct.
- **The 8 grading/authoring tools** (see [tools-reference.md](tools-reference.md)): preflight,
  occ_guard, hole_metrics, unit_normalize, regiondiff, perceive, surface_histogram, drawing_extract.
  Built + dogfooded + /review-hardened. Pure additions; not wired into the core reward.
- **The time-trial harness** (`timetrial/`): `grade_step.py` grades a pre-existing STEP through the
  SAME B-rep path as the AI's candidate (commensurable human-vs-AI scoring). The referee, not the
  thing measured. The trial itself (human modeller vs AI loop on trial_lbracket) is pending — needs
  a human + a fresh AI session that hasn't seen the GT.

## Tried and REJECTED (do not repeat)

- **CTC-05 hollow reconstructions.** ~12 manual hollow-variant edits all scored 0.41–0.69, BELOW
  the 0.688 solid-revolve + narrow-void. The part's upper body is NON-axisymmetric (material at
  both axis and rim at the same z = webs/lugs), so under cylindrical IoU a SOLID revolve beats any
  hollow — a wide open cavity that fixes volume craters IoU (0.18–0.32). The narrow short axial void
  is the optimum. Lesson: **measure per-band occupancy first** (`runs/_ctc05_ioucmp.py` pattern),
  don't thrash on hollow geometry.
- **Literal grooves on the CTC-05 outer profile.** LOWERED iou — a smooth taper matches the
  angle-collapsed voxel occupancy better than literal grooves. A full-profile retrace that held the
  wide radius hit +54% volume → 0.589, worse than baseline.
- **Face-adjacent section planes in the hole detectors.** Added to catch near-face blind holes;
  REVERTED — they section ~1.5mm off a face where edge-rounding / adjacent-hole-mouths project as
  near-circular loops and add phantom holes (regressed the L-bracket 4→5). The raised plane cap
  (13→64) is what actually fixed the large-part miss; the face planes were net-negative.
- **A phantom "euler hash-collision" bug.** Investigated and verified DOWN — OCC MapShapes confirms
  the counts are canonical-correct. Don't rewrite the counter.
- **The 2×2 eval-reproduction as the "prove AI CAD works" deliverable.** A /autoplan CEO review
  (dual-voice) rejected it: a geometric score vs hidden GT measures reconstruction fidelity, not
  engineer throughput, and its honest conclusion ("AI can't reliably read complex drawings")
  *supports* the skeptic. Pivoted to the time-trial (harness as referee). Kept as optional
  calibration evidence only.

## Deferred (the roadmap, ranked by leverage)

1. **Wire surface-histogram topology into reward.py** (the topology-ceiling fix). A held,
   reviewed PR-ready proposal: `build-specs/PROPOSAL_reward_topology_upgrade.md`. Hybrid Layer-4:
   `topo_s = 0.5 * exact_count_match + 0.5 * histogram_similarity`. Must be computed in the sandbox
   subprocess + serialised (OCP objects can't be pickled to the parent — same constraint as the
   existing topology signature). Ship the surface_histogram half; HOLD the hole_metrics half until
   its thin-wall bug is fixed. Has a 5-point regression plan. **Touches guarded code (reward.py +
   runner.py) — needs explicit approval before applying.** Highest leverage: it lifts the ceiling
   that caps every complex real part.
2. **B-rep cylinder-face hole detector** (the 4/6 fix). Count Cylinder faces + axes from the kernel
   instead of inferring circles from mesh sections — eliminates the thin-wall-parallel blind spot
   AND the intersecting-bore phantom in one primitive (limitations #5). New tool, not a patch. The
   `test_hole_metrics.py` 4/6 canary guards against silent drift until this lands.
3. **Run the actual human-vs-AI time trial.** The harness is built (`timetrial/`); needs a human
   modeller on trial_lbracket (timed, graded by `grade_step.py`) vs a fresh AI session (no GT seen),
   plus the revision round (bolt-circle Ø+4mm). Primary metric = turns-to-verified (deterministic);
   wall-clock secondary. See `timetrial/PROTOCOL.md`.
4. **Breadth: 30+ tasks.** Current suite is ~17 parts. Dataset shortlist: NIST PMI (done, all
   topology-capped), MFCAD++, ABC, DeepCAD. More low-face real parts = more solvable real wins.
5. **The surface-area-dominant reward gap** (FTC-09 box → siou 0.867). Feature-area weighting, or
   let the topology histogram carry it. See limitations #6.
6. **Drawing track depth.** `drawing_extract.py` wires the Gemini-2.5-flash vision reader
   (~77% dimension accuracy vs Claude ~40%) via `~/.banana/api_key`. Open: GD&T/tolerance extraction
   is the weakest area (~50%); the AP242 native-PMI oracle path executes as code but needs a
   semantic-PMI STEP outside ground_truth/ to confirm a non-empty result.
7. **Deferred follow-ons (bigger):** datum/chirality awareness; GD&T tolerance-aware scoring; no-GT
   grading (the hard one — verifying correctness without an answer-key STEP, which is what real
   engineering needs); a FreeCAD/CalculiX FEM + ocp-freecad-cam G-code "it's manufacturable" loop;
   a BYO-part + MCP grading server.
8. **Metric-authoring skill (Software 3.0 for the grader).** Stop hand-patching `harness/geometry.py`
   kernels (the round-part IoU has been fixed twice and a third degeneracy is now CONFIRMED — the
   abstraction keeps leaking; see item 9 + issue #7). A SKILL = (prompt + an accumulating property-based
   eval benchmark); an LLM GENERATES the deterministic kernel OFFLINE, you iterate the PROMPT until it
   passes every invariant, then FREEZE the produced python into `geometry.py`. Load-bearing: the LLM
   NEVER runs at grade time (determinism, limitations #9), and the skill PROPOSES — a human approves the
   guarded merge. Codex's warning: the grader IS the optimization target, so the benchmark must be
   property-based with adversarial false-positive cases, not case-based (else an overfit kernel trains
   agents toward wrong geometry while showing green). Full design: `docs/designs/metric-authoring-skill.md`.
   The `tasks/iou_benchmark/` property benchmark is **not yet built** — it is the skill build session's
   first deliverable.
9. **Round-part IoU tolerant fix (confirmed bug — limitations #2 / issue #7).** `_cylindrical_iou`'s
   shared `rmax` radial frame (`geometry.py:259`) is quantization-sensitive: two equal round annuli built
   different ways score `iou=0.78` (reproduced, `scripts/iou_roundpart_diag.py`). A ±1-bin dilation lifts
   the CHUNKY case (bearing_608, ~3:1) 0.78→0.93 — but it BREAKS thin high-aspect washers (FTC-11 class,
   ~15:1: wrong-bore scores HIGHER than correct), so the fix is **aspect-ratio-dependent and NOT yet
   solved**. Real FTC-11 could not be verified GT-free (its GT is under `ground_truth/`), so the bug's
   blast radius on solved parts is unknown. **Parked for a dedicated investigation + engineering-review
   pass** — the issue #7 handoff comment has the full data + open design questions (aspect-aware binning?
   density-normalized or banded radial comparison? does real FTC-11 even regress?). NOT 1-D marginals
   (they false-positive on stepped parts). Touches guarded `harness/geometry.py` — needs explicit
   approval once a cross-aspect fix is found.

## Where the deep research lives

Full research reports (OCC boolean robustness, complex-part reconstruction strategy, the
grading-frontier survey, the open-source AI-CAD landscape) are in the personal memory layer
(gbrain) under the `cad-autoresearch` slugs, and `build-specs/` holds the cold-executable
tool specs + the reward proposal. The `~/.claude/plans/` plan file carries the /autoplan review
trail for the time-trial pivot.
