# ARCHITECTURE

Reference for the CAD autoresearch harness. Audience: a future coding session
that opens this repo cold and needs to understand the system well enough to
**improve** it. Every claim here is traceable to source (file:line). When code
and prose disagree, the code wins — fix the prose.

Conventions and operating rules are in [`CLAUDE.md`](../CLAUDE.md) (repo map,
guardrails, branching) and [`program.md`](../program.md) (the worker prompt).
This doc does not repeat them; it documents the *architecture* and the *reward*.
The "why" behind the reward design, the known ceilings, the tool inventory, and
deferred research live in the sibling docs linked at the bottom.

---

## 1. What this is

A Karpathy-style AI-to-CAD autoresearch loop. A hidden ground-truth part exists
as a STEP file the agent never sees. Each turn an LLM (or an offline mock) writes
a [`build123d`](https://build123d.readthedocs.io/) program that assigns the final
solid to a variable named `result`. The harness runs that program in a sandboxed
subprocess, exports STEP + STL, and grades the result against the hidden ground
truth with a **deterministic** composite reward in `[0, 1]`. The agent receives
the score, a per-layer breakdown, rendered views, and a terse "what to fix next"
report, then iterates. The loop is verifiable-reward RL by hand: all intelligence
lives in the proposer, all truth lives in the reward.

---

## 2. The loop

One worker grinds one task. The driver is
[`run_inner_loop.py`](../run_inner_loop.py); the docstring at lines 4-15 is the
canonical pseudocode. The proposer seam is
[`loop/policies.py`](../loop/policies.py); the append-only experiment log is
[`loop/ledger.py`](../loop/ledger.py).

```
                          tasks/manifest.yaml + tasks/<id>/ground_truth/
                                          |
                                          v
  +-------------------+   task_view   +------------------+
  |   proposer        |<--------------|  run_inner_loop  |  load_task / load_ground_truth
  | loop/policies.py  |   + history   |  (one worker)    |  (run_inner_loop.py:43,52)
  |                   |-------------->|                  |
  | Mock | ClaudeCode |  Candidate    +------------------+
  +-------------------+  (.code)              |
                                             | code
                                             v
                                  +----------------------+
                                  | harness.run_candidate|  subprocess, timeout
                                  | harness/runner.py    |  writes result.step / .stl
                                  |                      |  + meta.json + topology.json
                                  +----------------------+
                                             | RunResult (mesh, topology, meta)
                                             v
                                  +----------------------+
                                  | harness.score        |  7-layer composite
                                  | harness/reward.py    |  RewardResult
                                  +----------------------+
                                             | composite + breakdown
                       +---------------------+---------------------+
                       v                                           v
            +--------------------+                      +----------------------+
            | render_compare     |                      | build_report         |
            | harness/render.py  |  PNGs                | harness/feedback.py  |  markdown
            +--------------------+                      +----------------------+
                       |                                           |
                       +---------------------+---------------------+
                                             v
                                  +----------------------+
                                  | ledger.consider/log  |  keep/discard + jsonl
                                  | loop/ledger.py       |  best/ snapshot if kept
                                  +----------------------+
                                             |
                                             v
                                  feedback.md -> history -> next turn (loop)
```

Per-turn sequence (`run_inner_loop.py:105-153`):

1. **propose** — `proposer.propose(task_view, history)` returns a `Candidate`
   (`code`, `meta`). Empty code -> skip, push a retry note into history
   (`:116-120`).
2. **build** — `run_candidate(cand.code, ws, timeout=args.build_timeout)`
   (`:122`).
3. **grade** — if the build succeeded, `score(run.mesh, gt_mesh,
   candidate_sig=run.topology, gt_sig=gt_sig, cfg=cfg)`; if it failed,
   `score(None, gt_mesh, ...)` which the body gate drives to 0 (`:123-128`).
4. **feedback** — `render_compare(...)` + `build_report(...)` (`:125,129`).
5. **keep/discard** — `ledger.consider(task, composite, min_delta)` then
   `ledger.log(...)` appends one jsonl row (`:131-136`).
6. **persist** — write `feedback.md`; if kept and a STEP exists, copy the STEP +
   candidate into `runs/<task>/best/` (`:138-144`).
7. **stop** — break when `composite >= args.target` (default `--target 0.97`,
   `:75`, `:150-153`).

The outer fan-out (`orchestrator.py`) and liveness/leaderboard (`watcher.py`)
sit above this; they are out of scope here (see [`CLAUDE.md`](../CLAUDE.md)
project map).

### The proposer seam (`loop/policies.py`)

Both proposers return `Candidate(code=..., meta=...)` (`policies.py:28-31`).
`make_proposer(kind, **kw)` dispatches (`:143-148`).

- **`MockProposer`** (`:66-76`) — deterministic, no API. Walks a 4-rung ladder
  (`_MOCK_LADDER`, `:37-63`) of hand-written build123d programs converging on the
  `sample_bracket` ground truth; clamps at the top rung. Drives the test suite
  and `--proposer mock`, exercising the whole loop offline.
- **`ClaudeCodeProposer`** (`:82-140`) — shells out to `claude -p` (headless),
  pointed at the repo with `--permission-mode acceptEdits` and a fixed
  `--allowedTools` set (`:93`, `:126-128`). It asks the CLI to write the next
  `candidate.py` to a known path and echo `CANDIDATE_WRITTEN`, then reads the file
  back (`:119-140`). One call == one turn; subagents the CLI spawns are invisible
  here.

### The ledger (`loop/ledger.py`)

Append-only jsonl, one line per attempt across all workers (`log`, `:55-70`):
`ts, task_id, worker, attempt, code_hash` (sha1[:12], `:38-40`), `code_len,
score, breakdown` (the full `RewardResult.to_dict()`), `kept, seconds, error`,
plus any `extra`. The keep/discard rule is `consider` (`:45-53`): accept iff
`score > best_so_far + min_delta`, updating best on accept. `best()` returns the
kept high-water mark (default `-1.0`). On construction the ledger **warm-starts**
from the existing file (`_warm_start`, `:28-36`) so a resumed run keeps its best.
Thread/process safety is by lock + append-only writes (`:48`, `:67-69`).

---

## 3. The reward (the heart)

[`harness/reward.py`](../harness/reward.py). `score(...)` (`reward.py:139`)
returns a `RewardResult`. The composite is a **body gate times a renormalised
weighted sum** of layers 2-7 (`:222-225`):

```
composite = body * ( Σ w_layer * score_layer ) / Σ w_layer
```

> **Heads-up (code vs naming):** the module docstring, `CLAUDE.md`, and
> `program.md` all say "six layers". There are **seven** — Surface IoU (`siou`)
> was added later as layer 7 (`reward.py:49`, `:126`, `:207-212`). The body gate
> is layer 1 and a multiplier, not a weighted term, so "6 weighted layers + 1
> gate" is the precise count.

### Weights (`RewardConfig`, read from source — `reward.py:44-49`)

| Field        | Value | Layer it weights        |
|--------------|-------|-------------------------|
| `w_volume`   | 0.20  | volume                  |
| `w_bbox`     | 0.15  | bounding box            |
| `w_topology` | 0.15  | topology (B-rep counts) |
| `w_iou`      | 0.25  | volumetric IoU          |
| `w_chamfer`  | 0.20  | Chamfer (surface dist)  |
| `w_siou`     | 0.10  | Surface IoU             |

Weights need not sum to 1; the composite renormalises by `Σ w` (`:221-224`). The
inline comments record the history: `w_iou` was cut from 0.30 to 0.25 to fund
`w_siou` (`:47`, `:49`).

### The body gate (layer 1)

`reward.py:158-166`. `body_ok` is true iff the candidate mesh is non-None, has
faces, **and** `G.volume(mesh) > 1e-9`. If not, `score` short-circuits and
returns `RewardResult(0.0, ...)` — every other layer is moot. So an empty /
degenerate / non-building candidate scores **0 overall**, no matter how good the
other numbers would have been. This is why a failed build is graded
`score(None, ...)` (`run_inner_loop.py:127`) rather than crashing the worker.

### Layers 2-7

Each layer is `[0, 1]`. Tolerance-band layers use `_ramp(err, soft, hard)`
(`reward.py:80-85`): `1.0` at `err <= soft`, `0.0` at `err >= hard`, linear
between.

| # | Layer        | What it measures | Tolerance band | Computed by (`geometry.py`) |
|---|--------------|------------------|----------------|------------------------------|
| 2 | **volume**   | symmetric relative volume error `|Vc-Vg|/max(...)` | soft `vol_tol_soft=0.01`, hard `vol_tol_hard=0.25` (`reward.py:36-37`) | `volume` (`geometry.py:23`), `relative_error` (`:48`) |
| 3 | **bbox**     | worst-axis relative error over **sorted** bbox extents (orientation-invariant) | soft `bbox_tol_soft=0.01`, hard `bbox_tol_hard=0.25` (`reward.py:38-39`) | `bbox_dims` (`geometry.py:32`, sorted ascending, prefers oriented bbox) |
| 4 | **topology** | weighted fraction of matching B-rep counts | exact-match (no ramp); see §5 | `topology_match` (`geometry.py:479`) |
| 5 | **iou**      | pose-invariant volumetric overlap | none (a ratio) | `iou` (`geometry.py:345`); routing in §4 |
| 6 | **chamfer**  | mean bidirectional surface nearest-neighbour distance, divided by the GT bbox **diagonal** to be unit-agnostic | soft `cham_tol_soft=0.005`, hard `cham_tol_hard=0.10` of diagonal (`reward.py:41-42`, applied `:201-204`) | `chamfer_distance` (`geometry.py:113`) |
| 7 | **siou**     | F1 of bidirectional surface-coverage fractions (recall = candidate points near GT surface; precision = GT points near candidate); catches a flat face where a curved one belongs | internal `threshold_frac=0.01` of diagonal, **floored** at ~1.5× sample spacing (`geometry.py:135`, `:166-178`) | `surface_iou` (`geometry.py:133`) |

Chamfer and SIoU both **centre** their point clouds first (`geometry.py:122-123`,
`:153-154`), so they measure shape, not placement — placement is the IoU's job.
The volume layer is **scale-correct** (never normalised away).

Sampling budgets (`RewardConfig`, `reward.py:51-53`): `n_points=8000` (Chamfer +
SIoU surface samples), `iou_points=60000` (Monte-Carlo interior fallback for IoU
only).

### `adaptive_feature_weighting` (AFW)

`reward.py:64-77` (config), `_adaptive_weights` (`:88-114`), applied at
`:218-220`. The measured problem (WF-M, 2026-05-30): on a part with many small
features (a hole field), volumetric IoU is the **only** layer that drops with
missing material; Chamfer and SIoU are structurally blind (a 7%-volume hole field
moves them less than the sampling floor), so a hole-less box scored high on the
surface terms. The fix shifts weight **out of the blind surface layers
(chamfer, siou) into the sensitive ones (iou, topology)** as the part gets more
feature-rich.

Mechanics, with the **real default values**:

- `afw_face_lo = 15` — at/below this GT B-rep face count, no shift (simple part).
- `afw_face_hi = 120` — at/above this, full shift (complex real part).
- `richness = clamp((gt_faces - 15) / (120 - 15), 0, 1)` — linear ramp
  (`:101-102`).
- `afw_max_shift = 0.10` — total weight moved at full richness; actual
  `shift = 0.10 * richness` (`:105`).
- The shift is **taken from** chamfer and siou in proportion to their current
  weights (`blind_total = chamfer + siou`, `:106`, `:110-111`).
- `afw_iou_share = 0.70` — of that shift, 70% goes to `iou`, the remaining 30% to
  `topology` (`:112-113`).

**It is keyed on the GROUND TRUTH face count, not the candidate's** (`gt_faces =
sig_g.get("faces")`, `reward.py:218`). A proposer therefore cannot game AFW by
adding faces to its own part — the weighting is fixed by the (hidden) answer.
Returns base weights unchanged when AFW is disabled, when `gt_faces` is `None`
(no B-rep signature), or when `richness <= 0` (`:99-104`).

### `RewardResult`

`reward.py:117-136`. Carries `composite` plus every sub-score (`body, volume,
bbox, topology, iou, chamfer, siou`) and a `raw` dict (candidate/GT volumes,
bbox, errors, the resolved signatures, the **actual weights used**, etc.). `siou`
defaults to `0.0` so old ledger rows written before layer 7 still deserialise
(`:126`). `summary()` is the one-line breakdown the feedback report prints
(`:132-136`).

---

## 4. The IoU routing subtlety

`iou(...)` (`geometry.py:345-398`) is rotation/translation-invariant volumetric
IoU. Anyone touching IoU must understand the routing.

**Occupancy is deterministic, not Monte-Carlo.** It voxelises each *filled* solid
via `_voxel_centers` (`geometry.py:316-342`) and IoUs the occupied-cell centres.
Determinism is the whole point: a self-comparison collapses to **exactly 1.0**,
removing the ~0.975 sampling floor that random interior points produced and that
made high-fidelity attempts indistinguishable from noise (`:317-324`, `:355-361`).
If voxelisation fails (e.g. a non-watertight candidate), it falls back to
Monte-Carlo interior sampling (`sample_volume`, `:377-385`) so a broken solid
still scores instead of crashing.

**Adaptive resolution.** With `target_pitch_mm` set (default `1.25` mm,
`reward.py:58`), the comparison-grid res is derived from the GT's longest extent
so the voxel pitch is ~`target_pitch_mm` regardless of part size:
`res = clamp(ceil(max_extent / target_pitch_mm), 24, res)` where the passed `res`
is the **cap** (`geometry.py:370-376`). So an 80 mm part -> res 64, a 40 mm part
-> 32, a 305 mm part -> capped at 64. A feature error smaller than the pitch is
invisible — that was the small-feature gradient gap this fixes. The actual
occupancy grid uses `res * 2` (`:377-378`).

**The round-vs-prismatic split.** After computing occupancy, `iou` calls
`_is_rotationally_symmetric` on **both** clouds (`geometry.py:390`):

- `_is_rotationally_symmetric(pts, tol=0.05)` (`:207-221`) sorts the covariance
  eigenvalues descending `w[0] >= w[1] >= w[2]`. Returns `True` if the two
  largest are within `tol` of each other — `(w[0]-w[1])/w[1] < 0.05` (a disc) —
  **or** the two smallest are — `(w[1]-w[2])/w[1] < 0.05` (a shaft). A prismatic
  part has three distinct eigenvalues -> `False`.
- If **both** clouds read symmetric -> `_cylindrical_iou` (`:224-277`):
  rotation-**invariant** IoU about each cloud's symmetry axis. It projects
  interior points to cylindrical `(radius, axial)` coordinates and IoUs the
  `(r × axial)` occupancy grids, collapsing the angular dimension so any in-plane
  rotation maps to the same grid. Two subtleties make a self-comparison score
  exactly 1.0: a **shared** `(r, axial)` frame derived from both clouds together
  (`:259`, `:270-271`), and a **2-way axial-sign search** because the symmetry
  axis is an eigenvector whose sign is arbitrary (`:269`).
- Otherwise -> the standard voxel path: `_canonical_frame` (PCA-align both,
  `:196-204`), then try all **48** signed orthogonal transforms on B
  (`_ortho_transforms`, `:300-313`) and keep the best `_voxel_iou`
  (`:393-398`). The 48 transforms (every axis permutation × every sign combo,
  including reflections) resolve the residual axis-sign/permutation ambiguity PCA
  leaves; reflections are deliberate so a symmetric part doesn't score false-low
  on an arbitrary PCA sign (chirality errors are caught by topology/chamfer
  instead, `:300-304`).

**Why this matters for editors:** the gate is keyed on *covariance eigenvalue
near-degeneracy*, not on the part being "round" in any intuitive sense. A regular
hexagon has 6-fold in-plane symmetry, so a hex prism reads `True` and takes the
cylindrical path (see `hex_bolt` and `slotted_ring` notes in
`tasks/manifest.yaml`). If you change the eigenvalue `tol`, you change which
parts route where.

---

## 5. The topology layer

B-rep topology signature. The full schema is
`{faces, edges, vertices, shells, solids, euler}` where `euler = V - E + F`
(`topology_signature_from_solid`, `geometry.py:404-443`). Euler is the single
most diagnostic number — a missing/extra through-hole shifts it by 2 — which is
why `topology_match` weights it **2×** (`:507`).

`topology_match(sig_a, sig_b)` (`geometry.py:479-510`):

- Returns **0.5 (neutral)** if either signature is missing (`:499-500`).
- **Cross-schema guard (read this before any topology up-weight).** A B-rep
  signature and the cheap mesh proxy share only the `euler` key, but the two
  `euler` values are *different quantities* (B-rep V-E+F over B-rep entities vs
  the triangulation genus of the mesh). Comparing them scores a geometrically
  **perfect** candidate `0.0`. So when one side is `brep` and the other is `mesh`
  the function returns **0.5**, not a spurious 0.0 (`:501-503`). Schema is
  classified by `_sig_schema` (`:468-476`) against `_BREP_SIG_KEYS =
  {faces,edges,vertices,shells,solids}` and `_MESH_SIG_KEYS =
  {components,watertight}` (`:464-465`).
- Same-schema (B-rep↔B-rep — the normal in-loop path; or mesh↔mesh): the weighted
  fraction of shared keys whose values match exactly, `euler` weighted 2×
  (`:504-510`). Falls back to equal-weight if `euler` is absent (e.g. an old
  `topology.json`).

`topology_signature_from_mesh` (`geometry.py:446-457`) is the proxy:
`{components, euler, watertight}` — a *different coordinate system* for topology,
used only when no B-rep is available.

**Why the signature is computed inside the sandbox.** The B-rep counts require
OpenCASCADE (OCP) `TopExp_Explorer` over the live solid, and **OCP objects cannot
be pickled back to the parent process**. So the runner computes the signature in
the subprocess and writes it to `topology.json`
(`runner.py:107-126`); the parent reads the JSON and passes it as
`candidate_sig` / `gt_sig` (`run_inner_loop.py:124`,
`reward.py:142-143`, `:182-191`). The sandbox's Euler formula `_v - _e + _f`
(`runner.py:122`) intentionally matches the grader's. Both the candidate (via the
sandbox) and the ground truth (via its prebuilt `topology.json`) therefore emit
the **B-rep schema**, so the normal in-loop comparison is B-rep↔B-rep — the
cross-schema guard only fires on the mesh-proxy fallback.

---

## 6. The task model

A task is the union of:

1. A `tasks/manifest.yaml` entry (`tasks/manifest.yaml`): `id`, `tier`
   (`easy|medium|hard`), `description`, `spec` (filename, spec track), optional
   `drawing` (filename, drawing track), `default_track`, `notes`.
2. A directory `tasks/<id>/` containing:
   - `ground_truth/result.step` + `result.stl` (the loaded mesh),
     `meta.json` (volume, bbox), `topology.json` (the B-rep signature).
   - `make_ground_truth.py` — the script that **generates** the GT (a build123d
     program for synthetic parts, or an ingest of an external `.stp` for the real
     NIST / bearing parts). It writes the four `ground_truth/` artifacts.
   - `spec.md` (spec track) and/or `drawing.png` (drawing track).

`load_task(task_id)` (`run_inner_loop.py:43-49`) reads the manifest, finds the
matching `id`, and stashes the resolved dir on `t["_dir"]`. `load_ground_truth`
loads `ground_truth/result.stl` into a trimesh mesh, reads `ground_truth/topology.json`
(tolerating a missing/corrupt file -> `sig=None`), AND computes the GT surface-type
histogram lazily from the re-imported `result.step` (cached by content; for the
hybrid Layer-4). It returns `(mesh, sig, gt_hist)` and raises a clear `SystemExit`
with the `make_ground_truth.py` command if the STL is not built. The track resolves to `--track` if given, else the task's
`default_track`, else `"spec"` (`:91`); the spec/drawing path is then passed into
the proposer's `task_view` (`:91-93`, `:107-112`).

The registry currently holds ~20 tasks: synthetic spec-track validation parts
(`sample_bracket`, `motor_mount`, `stepped_hub`, …), element probes
(`thinwall_box`, `twin_bodies`, `rib_probe`, `perf_plate`), real round parts
(`bearing_608`), and the real NIST PMI suite (`nist_ftc_11`, `nist_stc_06`,
`nist_ftc_07/09`, `nist_ctc_03/05`). The manifest `notes` are dense and worth
reading — many record *why* a part was chosen as a probe and which IoU path it
exercises.

---

## 7. The sandbox + candidate contract

[`harness/runner.py`](../harness/runner.py). A candidate is a Python program that
assigns the final solid to a module-level `result` — a build123d
`BuildPart`/`Part`/`Solid` or a CadQuery `Workplane`. Candidates **must not**
export or grade themselves; the harness appends that.

`run_candidate(code, workspace, timeout=120, python=None)` (`runner.py:149-200`):

1. Writes `candidate.py` = the proposer's code **+** `_SANDBOX_EPILOGUE`
   (`:30-131`), explicitly **UTF-8** (`:159`). UTF-8 is load-bearing on Windows:
   `Path.write_text` defaults to cp1252 there, so any non-ASCII char (em-dash,
   ⌀/° symbol in a comment) would be written as a byte Python refuses to execute
   as UTF-8 source — a cryptic `SyntaxError` graded as a build failure (`:155-159`).
2. Runs it in a **separate process** with a wall-clock `timeout` and an isolated
   `cwd`, with `AR_WORKSPACE` set in the env (`:161-169`). A timeout, kernel
   segfault, or runaway allocation degrades to a graded failure, not a dead
   worker (`:170-173`).
3. The epilogue (`__ar_export`, `:33-128`) resolves `result` into a solid
   (unwrapping a `BuildPart` context via `.part`, or a CadQuery `Workplane` via
   `.val()`, `:41-47`), runs a **validity gate**, exports `result.step` +
   `result.stl`, and writes `meta.json` (volume, bbox) and `topology.json`
   (B-rep signature). On success it prints the sentinel `AR_EXPORT_OK` (`:129`).
4. The parent treats a non-zero return code **or** a missing `AR_EXPORT_OK`
   sentinel as failure (`:176-179`), then loads the STL into a mesh (`:183-187`)
   and reads back the two JSON files (`:189-200`), returning a `RunResult`.

**The validity gate** (`runner.py:49-73`) catches degenerate/empty solids loudly.
OpenCASCADE can silently return an empty or fragment solid from a failed boolean
(no Python exception; `IsDone()` still True). Without the gate the harness would
export a degenerate STL and score it `body=1` off the fragment — a misleading
reward. The gate raises if `abs(solid.volume) <= 1e-6` (`:65-73`), so the
candidate is graded `body=0` with an actionable message. It deliberately uses
build123d's `.volume` (which sums a Compound's child solids) rather than raw
`BRepGProp.VolumeProperties_s(..., onlyClosed=True)`, which returns 0 on a
`TopoDS_Compound` and would falsely reject every valid multi-body part (`:56-64`).

`RunResult` (`runner.py:134-146`): `ok, workspace, step_path, stl_path, mesh,
topology, meta, stdout, stderr, error, seconds`.

---

## 8. Public API

`harness/__init__.py` (`harness/__init__.py:1-11`) re-exports the entire public
surface:

| Export | From | Role |
|--------|------|------|
| `run_candidate` | `runner` | sandboxed build + export |
| `RunResult` | `runner` | build artifacts dataclass |
| `score` | `reward` | the 7-layer composite grader |
| `RewardConfig` | `reward` | weights, tolerances, sampling, AFW knobs |
| `RewardResult` | `reward` | composite + per-layer breakdown + raw |
| `render_compare` | `render` | headless multi-view PNGs (candidate vs GT) |
| `build_report` | `feedback` | the per-turn markdown "what to fix" |
| `hints` | `feedback` | layer-keyed diagnostic strings |

`geometry.py` is **not** in the public API surface — it is the low-level
primitive layer that `reward.py` consumes (`reward.py:29`, `from . import
geometry as G`). Touch it through `reward.py`'s expectations.

---

## 9. Where to change what

| Goal | Edit | Notes |
|------|------|-------|
| Change a layer **weight**, tolerance band, sampling budget, or an AFW knob | `harness/reward.py` (`RewardConfig`, `reward.py:32-77`) | The composite math is `score()` (`:139`). |
| Add/modify a **geometric metric** (IoU routing, Chamfer, SIoU, topology, voxelisation) | `harness/geometry.py` | Keep self-comparison == 1.0 (or neutral) invariants; see §4–§5. |
| Change the **composite structure** (a new layer, the gate) | `harness/reward.py` **and** `harness/__init__.py` if it changes the public surface | Add the field to `RewardResult` with a default so old ledger rows still load (cf. `siou`, `:126`). |
| Change the **per-turn feedback** an agent sees | `harness/feedback.py` (`hints`, `build_report`) | Keep it terse — it re-enters context every turn. |
| Change the **sandbox/candidate contract** (export, validity gate, signature) | `harness/runner.py` (`_SANDBOX_EPILOGUE`) | The signature must stay schema-compatible with the grader (§5). |
| Change the **loop** (keep/discard, budget, target, persistence) | `run_inner_loop.py` + `loop/ledger.py` | `consider`/`log` are the acceptance + log seam. |
| Add a **proposer** | `loop/policies.py` (`make_proposer`) | Return a `Candidate(code, meta)`. |
| Add a **task** | new `tasks/<id>/` + an entry in `tasks/manifest.yaml` + a `make_ground_truth.py` | Then build the GT; never hand-author a spec by reverse-engineering a real part's STEP. |

### Guardrails (from [`CLAUDE.md`](../CLAUDE.md))

- **Never read anything under any `ground_truth/` directory.** It is the hidden
  answer key — the harness loads it, agents must not.
- **Worker agents do not edit `harness/`, `reward.py`, the orchestrator, or task
  ground truth.** The meta (outer-loop) agent may edit **only** `program.md`.
- Workers run **headless**, each in an **isolated run directory** — never point
  two workers at the same workspace.
- A build failure is graded **0, not crashed** (the body gate + subprocess
  timeout enforce this).

### Two things that surprise a naive reader

1. **`config.yaml`'s `reward:` block is not wired into the inner loop.**
   `run_inner_loop.py` constructs `RewardConfig()` with no arguments
   (`run_inner_loop.py:100`) — it never reads the `reward:` block from
   `config.yaml`. So `config.yaml:30` (`iou_res: 24`) is **dead** for the inner
   loop; the live values are the `RewardConfig` code defaults (`iou_res=64` cap,
   `iou_target_pitch_mm=1.25`, the weights above). If you want to retune via
   config, you must add the plumbing first, or change the dataclass defaults.
2. **"Six layers" everywhere, seven in code.** The reward header, `CLAUDE.md`,
   and `program.md` predate the SIoU layer. The running grader has seven (see §3).

---

## Sibling docs

- [`reward-design.md`](reward-design.md) — the *why* behind the reward: layer
  independence, the gate, why deterministic voxel IoU, why AFW is keyed on GT
  face count, the literature lineage (Onshape MCP rubric, EvoCAD).
- [`known-limitations.md`](known-limitations.md) — the ceilings and traps: the
  ~0.97–0.99 scoring ceiling for a perfect part, surface-layer blindness to
  small-fraction errors, the round-part / cross-schema topology history, the
  config-not-wired gotcha.
- [`tools-reference.md`](tools-reference.md) — the 8 grading/authoring tools.
- [`research-and-deferred.md`](research-and-deferred.md) — open questions,
  refuted probes, deferred reward work.
