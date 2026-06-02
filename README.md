# CAD Autoresearch

A Karpathy-style **autoresearch loop for AI-to-CAD**. Agents write `build123d`
programs that reconstruct a target part; a deterministic, six-layer reward grades
each attempt against a hidden ground-truth STEP; agents read the score + feedback
and iterate. An orchestrator fans the work out across a grid of parallel workers,
and each worker can spawn its own subagents.

The point isn't "ask a model to do CAD and hope." It's to **build the loop** —
verifiable reward, parallel search, tight feedback — and let it grind.

## The bet behind this

As of mid-2026, no one has solved autonomous drawing→CAD. Frontier models *execute*
CAD reliably from a good written spec, but they *misread engineering drawings* —
dimensions, GD&T, small features off a downsampled raster. The kernel isn't the
bottleneck; **reading the print is.** Reshef Elisha's Onshape MCP eval makes the
split concrete: with a human spec, easy parts score ~1.0; fully autonomous from a
drawing, hard parts score ~0.0.

Two consequences shape this repo:

1. **Reward is verifiable.** A CAD reconstruction can be graded against ground
   truth geometrically (volume, bbox, IoU, topology, Chamfer). That's exactly the
   condition where an autoresearch loop pays off — the agent can measure "closer
   or not" without a human in the loop.
2. **Separate the two jobs.** A **spec track** (given a written spec → pure
   execution) and a **drawing track** (given only an image → must read it first).
   Keeping them apart lets you see whether a failure is a modelling miss or a
   vision miss, and lets you throw a dedicated vision subagent at the hard half.

## What's in the box (and verified working)

The harness runs end-to-end. Offline, with the deterministic mock proposer
climbing toward the sample part:

```
attempt 001 KEPT  composite=0.123 [vol=0.000 bbox=0.000 topo=0.400 iou=0.210 cham=0.001]
attempt 002 KEPT  composite=0.862 [vol=0.842 bbox=1.000 topo=0.400 iou=0.961 cham=0.975]
attempt 003 KEPT  composite=0.878 [vol=0.921 bbox=1.000 topo=0.400 iou=0.958 cham=0.979]
attempt 004 KEPT  composite=0.990 [vol=1.000 bbox=1.000 topo=1.000 iou=0.975 cham=0.985]
TARGET HIT (0.990 >= 0.97) in 4 attempts
```

`pytest -q` passes: body gate rejects empty solids, identical geometry scores
>0.9, wrong-size scores lower, and the sandbox runner builds + grades two
candidates of increasing fidelity monotonically.

## Install

```bash
bash scripts/setup.sh
```

That installs deps, builds the sample ground truth, and runs the offline smoke
test. Manual equivalent:

```bash
pip install -r requirements.txt          # add --break-system-packages on Debian/Ubuntu
python tasks/sample_bracket/make_ground_truth.py
python run_inner_loop.py --task sample_bracket --proposer mock --budget 5
```

Needs Python **3.10–3.13** (build123d 0.10 requires `<3.14` — the OCP wheels stop at
3.13; on 3.14 the install fails on the OCP wheel). The clean path is
`uv venv --python 3.13 && uv pip install -r requirements.txt`. `build123d` pulls
OpenCASCADE (OCP) — a large wheel, give it a minute.

## Quickstart — offline, no API

The mock proposer exercises the entire loop (execute → grade → render →
keep/discard → ledger) with zero API calls. Use it to confirm your environment and
to develop the harness:

```bash
python run_inner_loop.py --task sample_bracket --proposer mock --budget 6
```

Outputs land in `runs/sample_bracket/`: per-attempt workspaces with `result.step`,
`result.stl`, four-view render PNGs, a `feedback.md`, the `ledger.jsonl`, and the
kept `best/`.

## Run it for real — the grid

```bash
# launch N workers per task (each isolated), then watch
python orchestrator.py --proposer claude --workers 4 --tasks sample_bracket --model opus
python watcher.py
```

- **Backend.** `--backend tmux` (default in config) gives one window per worker in
  a detachable session; `--backend subprocess` runs background processes with
  per-worker logs and works anywhere (including Windows/WSL).
- **Dry run.** `python orchestrator.py --dry-run` prints the exact commands and
  launches nothing.
- **Aggregate.** `python orchestrator.py --aggregate-only` rebuilds the global
  per-task leaderboard and promotes the best STEP to `runs/<session>/<task>/BEST/`.

Requires the Claude Code CLI on `PATH`, signed in to your plan (`claude login`). **No
API key needed** — the proposer drives `claude -p`, which bills your subscription via
OAuth. In fact `ANTHROPIC_API_KEY` is *scrubbed* before each `claude` spawn (it would
otherwise be preferred and silently bill the metered API); the launcher prints which
billing plane is active.

## The two tracks

| Track   | Input                      | What the agent must do                          | Where it's hard |
|---------|----------------------------|-------------------------------------------------|-----------------|
| spec    | `spec.md` (written intent) | translate spec → build123d                      | rarely; pure execution |
| drawing | `drawing.png` only         | read the drawing → derive spec → build123d      | the real wall: dimension/GD&T reading |

Set per task with `default_track` in `tasks/manifest.yaml`, or force with
`--track spec|drawing`. On the drawing track, workers are told to route the
reading through `prompts/vision_subagent.md` first.

## The reward (what you're optimising)

Composite ∈ [0,1], a weighted blend of six independent layers (defaults in
`harness/reward.py:RewardConfig`):

| Layer    | Weight | Measures                                             |
|----------|:------:|------------------------------------------------------|
| body     | gate   | a valid watertight solid exists at all (else ~0)     |
| volume   | 0.20   | total volume vs GT (catches missing/extra material)  |
| bbox     | 0.15   | sorted bounding-box extents (the envelope)           |
| topology | 0.15   | exact B-rep face/edge/vertex counts (small features) |
| iou      | 0.30   | pose-invariant volumetric overlap (gross shape)      |
| chamfer  | 0.20   | fine surface agreement (radii, exact positions)      |

Pose invariance is real: the IoU centres + PCA-aligns both solids and searches all
48 signed orthogonal transforms, so a correct part placed at a different
origin/orientation still scores ~1.0. Identical geometry caps at ~0.97–0.99 (a
sampling-spacing floor on Chamfer/IoU), so treat **composite ≥ ~0.95 as "solved"**,
not 1.0.

**The one knob that matters:** the quality of the *input* (which track, and how
good the spec / how readable the drawing) dominates everything. After that, the
IoU point budget (`reward.iou_points`) trades grading speed against score noise —
60k is self-consistent; drop it for faster turns on big grids.

## Adding real parts

The sample bracket is a toy to prove the pipeline. For real work, add tasks built
from NIST PMI, SolidWorks Model Mania, ABC, DeepCAD, or Fusion 360 Gallery — see
`scripts/DATASETS.md` for sources, a STEP→task recipe, and licensing notes. Match
their easy/medium/hard banding in `tier:` so your numbers are comparable to
published benchmarks.

## The agent hierarchy ("agents spawning agents")

```
orchestrator.py                      fans out the grid
  └── worker × N per task            run_inner_loop.py, ISOLATED workspace each
        └── subagents per turn       vision (read drawing) / debugger (fix build), via Task
  └── watcher.py                     keeps it looping; optional META agent (outer loop)
        └── meta agent               edits program.md to unstick a plateaued grid (experimental)
```

That's up to four levels: orchestrator → workers → subagents, plus an optional
bilevel outer loop. Scale `--workers` to your machine and API budget.

## Isolation is load-bearing (a hard-won lesson)

Every worker gets its **own** run directory — separate ledger, separate candidate
workspaces, separate `best/`. This isn't tidiness; concurrent CAD-eval agents that
share a directory **clobber each other's files** mid-build. (This harness was
itself built next to a parallel agent that did exactly that.) If you extend the
orchestrator, keep workers isolated and aggregate after.

## Billing caveat

From **2026-06-15**, headless `claude -p` / Agent SDK usage on subscription plans
draws from a separate monthly Agent SDK credit allotment. An overnight grid is many
headless turns — check your plan's limits before launching hundreds of worker-turns.

## Deeper documentation (`docs/`)

For anyone (human or a future AI session) picking this up to *improve the harness*,
`docs/` holds the architecture + the hard-won knowledge that isn't obvious from the code:

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — reference: the loop, the 7-layer
  reward with exact weights, the IoU routing, the topology layer, the task model, the
  sandbox/candidate contract, and a "where to change what" map.
- **[docs/reward-design.md](docs/reward-design.md)** — *why* the reward is shaped this
  way: independent layers, the weight rationale, adaptive feature-weighting, the ramps.
- **[docs/known-limitations.md](docs/known-limitations.md)** — the landmine map: the
  topology ceiling, round-part IoU, OCC silent booleans, STEP seam-edge merge, the
  mesh-section hole-detection limits, the small-feature gap, the dead `config.yaml`
  reward block. **Read before concluding "low score = bad reconstruction" — often it's
  the reward.**
- **[docs/tools-reference.md](docs/tools-reference.md)** — the 8 grader-side / authoring
  tools (preflight, occ_guard, hole_metrics, unit_normalize, regiondiff, perceive,
  surface_histogram, drawing_extract): CLI, API, known limits, GT-leak boundaries.
- **[docs/research-and-deferred.md](docs/research-and-deferred.md)** — what's solved,
  what was tried and rejected (don't redo it), and the ranked deferred roadmap.

## Honest limitations

(See [docs/known-limitations.md](docs/known-limitations.md) for the full, code-traced list.)

- **The drawing track is unsolved by design.** This repo gives you the loop and the
  reward to *attack* it; it does not magically read dense drawings. Expect the
  vision subagent to be where most of your iteration goes.
- **The mesh-based reward** is robust and fast but not a substitute for
  feature-tree / manufacturing-intent comparison. Topology counts catch missing
  features; they don't verify *how* a feature was modelled.
- **Single-CPU grading** of dense IoU is ~1–2s/attempt; fine for a laptop grid,
  worth profiling (and lowering `iou_points`, or adding `embree`/`rtree`) for very
  large runs.
- **CadQuery** candidates are supported by the runner but the prompts and
  cheat-sheet are written for build123d.
