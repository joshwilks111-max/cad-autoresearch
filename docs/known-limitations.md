# Known limitations & landmines

The hard-won knowledge a future session needs to *not* re-discover the slow way. Each
item below cost real debugging time. Read this before changing the reward, the geometry,
or the hole detectors — and before concluding "a part scores low, the reconstruction must
be wrong" (often the reward is the thing that's wrong).

This is an **explanation** doc (the *why* behind the scores and the traps). For the layer
mechanics see [ARCHITECTURE.md](ARCHITECTURE.md); for the reward design rationale see
[reward-design.md](reward-design.md).

---

## 1. The topology ceiling — high-face real parts cap ~0.88 regardless of geometry

**The single most important thing to understand about the scores.** The topology layer
matches EXACT B-rep counts; at the adaptive weight a feature-rich GT carries (~0.18 for a
156-face part), a perfect revolve that produces ~57 faces against a 156-face GT scores
`topo ≈ 0.29`, which alone caps the composite around **0.88 even with otherwise-perfect
geometry**.

- **Measured:** CTC-05 (156 GT faces) caps ~0.88; reconstructed to 0.688 (geometry-near-best
  for the revolve family). FTC-09 (163 faces) → 0.758. STC-06 (144 faces) → 0.628.
- **Low-face real parts are the opposite:** bearing_608 (4 faces) → **0.997**; FTC-11 washer
  (6 faces) → 0.956. These match the GT B-rep graph exactly, so topo = 1.0.
- **Consequence:** treat ≥0.95 as "solved." A complex real part stuck at 0.6–0.7 with
  `vol/bbox≈1.0` and low `topo` is **topology-capped, not badly reconstructed** — do not
  burn turns trying to push its geometry. Confirm by reading the layer breakdown: if
  `topo` is the floor and `vol`/`bbox` are ~1.0, you've hit the ceiling.
- **The real fix** (deferred, reviewed): a kernel-stable surface-type histogram instead of
  exact counts — see [research-and-deferred.md](research-and-deferred.md) and
  `build-specs/PROPOSAL_reward_topology_upgrade.md`. The tool exists (`surface_histogram.py`),
  the reward wiring is a held proposal.

## 2. Round / annular parts: cylindrical IoU, not voxel IoU

A rotationally-symmetric solid (washer, bushing, bearing) has an **arbitrary in-plane PCA
frame** — the 48-transform voxel-IoU alignment search can't lock its rotation, so a perfect
round part scored a false-low volumetric IoU (~0.62) for a long time.

- **Fix (shipped):** `geometry._is_rotationally_symmetric` (two near-equal PCA eigenvalues
  within tolerance) routes round parts to `_cylindrical_iou` — radius × axial occupancy
  about the symmetry axis, with a shared (r, z) frame + axial-sign search. FTC-11 washer
  IoU 0.619 → 0.986; it became the first solved real NIST part purely from this reward-bug fix
  (the candidate was byte-identical).
- **Landmine:** the symmetry detector mis-routes **near-equal-extent prismatic parts** (e.g.
  a part that is coincidentally ~square in two axes). For the time-trial part this was avoided
  by choosing DISTINCT extents (120/60/44, eigenvalue ratios 1:2.8:13) so it takes the voxel
  path unambiguously. If you author a new task and its IoU looks wrong, check which branch it
  took first.

## 3. OCC silent boolean failures

build123d / OpenCASCADE booleans (`cut`/`fuse`/`intersect`) **return `IsDone()==True` on
garbage** — an empty solid, a fragment, or the unchanged base. No exception is raised. A
naive harness then tessellates the fragment and scores `body=1` off a stale/partial mesh.

- **Harness mitigation (shipped):** the sandbox validity gate fails degenerate/empty solids
  with `body=0` and a clear error. **Use build123d `.volume`, NOT `BRepGProp(..., onlyClosed=True)`**
  — the latter returns 0 on a Compound and false-positives every complex part.
- **Authoring mitigation:** `occ_guard.py` wraps the booleans and raises loudly on
  empty/zero-volume OR fragmentation (result has more disjoint solids than the base). It does
  NOT reject large material removal — hollowing/shelling routinely removes >50% and is valid
  (an earlier 50%-volume gate falsely rejected those; fixed in review).
- **`HasErrors`/`HasWarnings` are NOT exposed** on `BRepAlgoAPI_*` in this OCP build
  (`hasattr → False`), which is why the guard uses a volume + solid-count proxy.
- Sub-body architecture (revolve/extrude each feature, then batch the cuts into one compound)
  is the robust modelling pattern that avoids most silent failures.

## 4. STEP export→import merges seam edges (kernel/style instability)

A byte-identical STEP export→re-import **changes B-rep counts**: the L-bracket goes 51→49
edges, 34→32 vertices on the round-trip (OCC merges seam edges). This breaks exact-count
topology matching against a part that was signed in-memory.

- **Consequence for task authoring:** sign `topology.json` from the **RE-IMPORTED** STEP, not
  the in-memory solid — otherwise a perfect submission scores topo < 1.0 (the L-bracket signed
  in-memory scored topo 0.714; signed from the re-imported STEP → 1.000). See
  `tasks/trial_lbracket/make_ground_truth.py` for the pattern (and the comment block there).
- **This is the second reason** the surface-type histogram (limitation #1's fix) is the right
  long-term topology layer: a face's surface TYPE is invariant to seam merges, so the histogram
  is identical across the round-trip (verified: {Plane:13, Cylinder:4} in-memory == re-imported,
  where edge counts shifted 51→49).

## 5. Mesh-section hole detection is approximate (the 4/6 ceiling)

`regiondiff.py` and `hole_metrics.py` detect holes by sectioning the mesh and finding circular
inner loops. This works for axis-aligned holes through a non-thin feature, but has a real,
characterized failure class:

- **Holes through a THIN WALL, running PARALLEL to the part's deep axis, are invisible.** The
  L-bracket has 6 holes (4 base along Z + 2 wall along Y); both detectors find **4/6**. A
  constant-Y section through the 8mm wall returns the wall's OUTER rectangle (1 loop), not the
  two bores as closed inner circles — the plane slices *along* the bore length, so the bore is
  a boundary perturbation, not a closed loop. Verified: Y=26 section = 1 loop, area 5280 = the
  120×44 wall face.
- **What was fixed in review:** all-3-axis sweep (was long-axis only); dense ~4mm planes with a
  64-plane cap (was 3 bbox fractions — missed thin features in tall parts); ≥2-plane per-axis
  confirmation (kills cross-axis tangential-graze phantoms); cv<0.15 circularity gate (an
  earlier dead `cv_max` param let gusset-junction loops through as phantom r=11 "holes"); 3D
  world-center matching for cand-vs-GT diff. Both detectors went 0/6 → 4/6 on the L-bracket.
- **Also a phantom class:** two *intersecting* bores carve a cross-shaped cavity whose section
  loops can be near-circular enough to pass cv<0.15 and register as extra "holes." Intermittent
  (geometry/tessellation dependent).
- **The robust fix (deferred):** a different primitive — count B-rep Cylinder faces + their axes
  straight from the kernel (the way `surface_histogram.py` walks faces), instead of inferring
  circles from mesh sections. That's a NEW tool, not a patch. There is a `tests/test_hole_metrics.py`
  **4/6 canary** that trips if either detector silently drifts off 4 — update it the day a B-rep
  detector lands.

## 6. The small-feature precision gap (mostly fixed; one case open)

A 1mm shift of features covering <5% of the surface used to score ~0.991 — no gradient for the
agent to climb, because Chamfer and Surface-IoU under-resolve small features and the IoU grid
was too coarse.

- **Fix (shipped):** adaptive IoU pitch — `iou_target_pitch_mm=1.25`, res derived per-part as
  `clamp(max_extent/1.25, 24, 64)`. A 1mm rib shift now moves IoU 0.992 → 0.900 (verified by
  hand). Cost: 11–18× the IoU layer vs flat-low-res, but only on parts big enough to need it.
- **The unifying finding behind several of these:** the reward under-weights **small-FRACTION
  errors** (a missing hole is a tiny fraction of volume/area/face-count). IoU is the only layer
  that tracks missing material ~proportionally; Chamfer and SIoU are structurally floor-blind to
  it. That's WHY `adaptive_feature_weighting` shifts weight INTO iou+topology as GT face count
  rises (keyed on the GT so it's ungameable). See [reward-design.md](reward-design.md).
- **Still open:** the surface-area-dominant case (FTC-09 box-approx scored siou 0.867 — a large
  flat face fools chamfer+SIoU). Candidate fixes: feature-area weighting, or the topology histogram.

## 7. The grade ceiling is ~0.97–0.99, not 1.0

Even a perfect part rarely scores exactly 1.0 — IoU/chamfer sampling has a floor (finite voxel
pitch + finite surface samples), so a flawless reconstruction lands ~0.97–0.99. **Treat ≥0.95
as solved; do not chase the last 0.03** — it's sampling noise, not reconstruction error.

## 8. `config.yaml`'s `reward:` block is DEAD for the inner loop

`run_inner_loop.py` constructs `RewardConfig()` with **no arguments** (~line 100) — it never
reads `config.yaml`'s `reward:` section. So editing reward knobs in `config.yaml` (e.g.
`config.yaml` sets `iou_res: 24`) has **no effect on the single-worker loop**; the live values
are the dataclass defaults in `reward.py` (e.g. `iou_res=64` at `reward.py:53`).

- **Consequence:** to actually change reward behavior, edit the `RewardConfig` defaults in
  `harness/reward.py`, NOT `config.yaml`. A future session retuning via `config.yaml` will see
  no change and waste time hunting for why.
- (The orchestrator grid path may consume config.yaml differently; verify before relying on it.
  The single-worker `run_inner_loop.py` path definitively ignores the reward block.)
- **Naming drift to know about:** `reward.py`'s header, `CLAUDE.md`, and `program.md` all say
  "six layers" — the running grader has **seven** (Surface IoU / `siou` was added after those
  were written). Code is authoritative: 6 weighted layers + 1 body gate.

## 9. Determinism (don't reintroduce non-determinism into a grader)

The reward is deterministic by design: IoU uses a fixed seed and an RNG-free voxel-center path;
`sample_surface` restores the global RNG after use. Verified byte-identical run-to-run. If you
add a layer or tool, keep it deterministic — a grader that scores the same candidate differently
on re-run is unusable for the loop. (Pin tessellation tolerance too: GT/candidate must tessellate
at the same tolerance — the harness uses 0.05 throughout; `grade_step.py` and the STEP-loading
tools match it.)

---

## Quick triage: "this part scores low, is it the reconstruction or the reward?"

1. Read the layer breakdown (`grade_one.py` prints it, or `RewardResult.summary()`).
2. If `topo` is the floor and `vol`/`bbox` ≈ 1.0 → **topology ceiling** (#1). It's not the
   geometry. Stop pushing.
3. If `iou` is low on a ROUND part → check it took the cylindrical branch (#2).
4. If `body=0` → the candidate built an empty/fragment solid (#3); run `preflight.py` to see.
5. If a hole-count term looks wrong → mesh-section limits (#5); the 4/6 ceiling is expected on
   thin-wall-parallel bores.
6. If the score won't move on a 1mm feature shift → small-feature gap (#6), check the IoU pitch.
