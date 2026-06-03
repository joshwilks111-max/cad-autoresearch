# program.md — CAD Autoresearch Worker

> This is the **prompt that one worker agent reads and follows**, the direct
> analog of Karpathy's `program.md`. **You (the human) iterate on THIS file.**
> **The agent iterates on the candidate program (`candidate.py`).** That division
> is the whole method: tighten the instructions here when the agents get stuck in
> a way no single code change fixes; let the agents grind the geometry.

## Your job

You are one worker in a grid. You are handed a CAD task and must produce a
**build123d program** that reconstructs the target part as closely as possible.
You will be graded by a hidden, deterministic reward function (see "How you're
scored"). You do **not** get to see the ground truth. You get a **score** and a
**feedback report** after each attempt, and you iterate.

Reconstruct the part. Maximise the composite score. Stop when you reach the
target or exhaust your budget.

## The loop (what happens each turn)

1. You read the task spec (and/or the drawing image) and the feedback from your
   last attempt.
2. You write a complete build123d program to the path the harness gives you,
   assigning the final solid to a variable named **`result`**.
3. The harness runs it in a sandbox, exports STEP + STL, and grades it.
4. You receive a score breakdown + targeted hints + rendered views.
5. Go to 1. Keep what worked, change what didn't. This is propose → execute →
   evaluate → keep/discard.

## Two tracks — know which one you are on

- **spec track** — you are given a human-written geometry spec (`spec.md`). This
  is pure execution: translate the spec into correct build123d. With a good spec,
  near-perfect scores are achievable. No excuses on this track.
- **drawing track** — you are given ONLY a 2D engineering drawing image. You must
  first *read the drawing* — extract every dimension, hole, fillet, chamfer, and
  GD&T callout — and write your own internal spec before modelling. **This is the
  hard part and where models fail.** Treat reading the drawing as a distinct,
  careful sub-task (see "Spawning subagents").

The feedback report tells you which track you are on by what input it references.

## The candidate contract (non-negotiable)

- The program **must** define a module-level variable `result`.
- `result` may be a build123d `BuildPart` context, a `Part`/`Solid`, or a
  CadQuery `Workplane`. The harness resolves all three.
- **Do not** call `export_step` / `export_stl` yourself — the sandbox does it.
- **Do not** read anything under any `ground_truth/` directory. It is hidden for a
  reason; trying to read it is cheating and will be treated as a failed attempt.
- **Do not** run the grader, the loop, or the orchestrator. Write the program;
  the harness grades it.
- Keep the program self-contained and deterministic (no randomness, no network,
  no reading of other candidates).
- Units are **millimetres** unless the spec says otherwise. If the drawing is in
  inches, convert (×25.4) and say so in a comment.

## How you're scored (optimise this, in this order)

The composite ∈ [0,1] is a weighted blend of six layers. Earn them roughly in
this order — each unlocks the next:

1. **body** (gate) — produce a valid, watertight solid. A program that raises or
   yields no solid scores 0 overall. Get *something* that builds first.
2. **bbox** — overall bounding box (sorted extents). Nail the outside envelope.
3. **volume** — total volume. Catches missing/extra material and polarity errors.
4. **iou** — pose-invariant volumetric overlap. Rewards getting the gross shape
   and proportions right.
5. **topology** — exact face/edge/vertex counts. This is where small features
   live: every missing fillet, chamfer, or hole shows up here.
6. **chamfer** — fine surface agreement. The last few percent: exact radii and
   feature positions.

Practical consequence: **get a building solid with the right envelope first**,
then **match volume and gross shape**, then **add every feature** (holes, slots,
pockets), then **refine radii and positions**. Don't polish fillets while the
bounding box is still wrong.

## Reading the feedback report

Each turn you get something like:

```
**Score:** composite=0.862 [body=1 vol=0.842 bbox=1.000 topo=0.400 iou=0.961 cham=0.975]
**What to fix next:**
- Topology differs (candidate vs GT): {'faces': (7, 15), ...}. A face/edge-count
  gap usually means a missing fillet/chamfer, a missed hole, or a feature merged
  where it should be separate.
**Renders (candidate vs ground truth):** ...png
```

- The **lowest sub-score is your target.** Here topo=0.400 → features are
  missing; faces 7 vs 15 → add the holes/slot.
- **Look at the renders.** Compare your part to ground truth view by view. Numbers
  tell you *that* something's wrong; the images tell you *what*.
- A **build failure** report includes the stderr tail — fix the actual error
  before trying anything ambitious.

**The hints name your failure types — match each phrase, apply its fix.** "What to
fix next" is generated from your scores; it may list one hint or several. Work the
lowest-layer one first (a build failure before a missing feature, a missing feature
before a fillet radius) — don't try to fix everything in a single turn:

| If the hint says… | It means | Do this |
| --- | --- | --- |
| **No valid solid was produced** | build raised / `result` unset | read the stderr; get *anything* watertight before anything ambitious |
| **SOLID COLLAPSED: candidate volume is only X%** | a boolean failed (degenerate, not erroring) — NOT a missing feature | build independent sub-bodies and fuse once at the end; batch SUBTRACT cuts; revolve cones/spheres instead of primitive booleans |
| **Volume is X% OVER** | feature polarity — a cut modelled as a boss, or a hole not cut | flip the polarity (SUBTRACT vs ADD) on the offending feature |
| **Volume is X% UNDER** | a missing feature, an over-aggressive cut, or wrong wall thickness | add the missing material / check cut depths + thickness |
| **Bounding box mismatch** | overall dims or units wrong | re-check the envelope; suspect inch→mm conversion |
| **Topology differs (candidate vs GT)** | a missing fillet/chamfer/hole, or a feature merged that should be separate | add the small features; keep features separate where the GT does |
| **Low volumetric IoU** | gross shape is off | STOP tweaking details — re-read the primary profile/sketch first |

Same discipline as the score order: get a building solid → right envelope →
volume/gross shape → every feature → radii. One hypothesis per turn; don't regress
a layer you already earned.

## Spawning subagents (you may, and on the drawing track you should)

You have the `Task` tool. Decompose when it helps:

- **Vision subagent** (drawing track): hand it `drawing.png` and the instructions
  in `prompts/vision_subagent.md`. Its only job is to return a precise, structured
  geometry spec (every dimension + feature + datum). Reading the drawing carefully
  is a separate skill from modelling — isolate it so a modelling mistake doesn't
  contaminate your reading of the print, and vice versa.
- **Debugger subagent**: when a build fails with a kernel/selector error you can't
  immediately parse, hand the failing `candidate.py` + stderr to a subagent using
  `prompts/debugger_subagent.md` and get back a minimal fix.

Spawn freely, but converge: the deliverable is always a single `candidate.py` with
`result` defined. Don't fan out so wide you never write the program.

## build123d cheat-sheet (the 90% you need)

```python
from build123d import *

with BuildPart() as p:
    Box(80, 50, 8)                      # length(X), width(Y), height(Z), centred
    Cylinder(radius=5, height=20)       # centred on origin by default

    with Locations((20, 0, 0), (-20, 0, 0)):   # place features at points
        Hole(radius=2.5)                # through-hole at current locations
        # CounterBoreHole(radius, counter_bore_radius, counter_bore_depth)
        # CounterSinkHole(radius, counter_sink_radius)

    with BuildSketch():                 # a sketch to extrude/revolve
        Rectangle(30, 10)
        # Circle(radius=4); SlotOverall(width, height); RegularPolygon(r, n)
    extrude(amount=-8, mode=Mode.SUBTRACT)   # ADD | SUBTRACT | INTERSECT

    fillet(p.edges().filter_by(Axis.Z), radius=3)     # round edges
    chamfer(p.edges().group_by(Axis.Z)[-1], length=1) # bevel edges

result = p                               # REQUIRED
```

Selectors (for fillet/chamfer/locating): `p.edges()`, `p.faces()`,
`.filter_by(Axis.Z | GeomType.CIRCLE | Plane.XY)`, `.group_by(Axis.Z)[-1]`,
`.sort_by(Axis.Z)`. When a selector grabs the wrong edges, inspect with a render
and narrow it — bad selectors are the #1 cause of "fillet applied to the wrong
edge" topology errors.

Polarity is the #1 silent error: a feature that should remove material must use
`Mode.SUBTRACT` (or `Hole`, which subtracts). If your volume comes back *over*
ground truth, you probably added where you should have cut.

### When a chamfer/fillet build FAILS ("Failed creating a chamfer, try a smaller length")

This OCC error has two common causes, so fix them in cost order:

1. **The length really is too big** for the local geometry — a chamfer/fillet
   bigger than the adjacent face width, a short edge, a nearby hole, or a concave
   corner. This is the CHEAP check: try a smaller length once. If it now builds,
   you're done.
2. **The selector grabbed the wrong edges** — if shrinking the length does NOT
   help (it still fails at 0.4, 0.2), the edge is the problem, not the size. A
   frequent culprit is an edge at a *fusion junction* (where two bodies were
   joined and one face was consumed): after the fuse it may be partially interior,
   which OCC often cannot chamfer. Re-pick instead of shrinking further.

- **Re-pick the edges** (when smaller-length didn't help). Select the edge by an
  *unambiguous* geometric predicate (a specific `group_by(Axis.Z)` band AND a
  `filter_by` on type/position), and prefer edges on a *free outer boundary* over
  an internal junction. Verify the selection (render it / count it) before
  re-applying.
- **An "optional" or "flavour" feature is not worth a failed build.** If the spec
  marks a small chamfer/fillet as optional and it keeps breaking the build, **drop
  it and ship the rest** — a body=0 (build failure) scores **0 overall**, whereas
  omitting one small chamfer costs only a sliver of the topology + chamfer layers.
  A watertight part missing one optional bevel beats a part that won't build. Add
  the optional feature back only once the rest is solving ≥ target.

### When topology is stuck (faces/edges a little OVER ground truth) but geometry is right

If `vol` and `bbox` are ~1.0 and the renders look correct, yet `topo` is stuck
(your face/edge count is a few ABOVE GT — e.g. faces 19 vs 17), a frequent cause is
**fusion seams**: when you build a feature as a *separate body* and ADD/fuse it onto
another, OCC can leave a seam edge that splits one logical face into two, inflating
the count (it can also come from split sketch wires, boolean history, or a feature
modelled as a different surface type than GT — so confirm with the renders + the
topology delta first). When the exporter merges coplanar seams on the GT side but
your in-memory part keeps them, you read a couple of faces high. To close it:

- **Build naturally-continuous geometry as ONE sketch, not several fused bodies.**
  E.g. an L-bracket's base plate + upright wall share the full part width — model
  them as a single **L-shaped profile** (a sketch on the side plane) **extruded
  along the shared axis**, so the plate↔wall junction is one continuous solid with
  NO fuse seam. Only genuinely-separate features (a narrow centred gusset rib, a
  boss) remain as added bodies.
- **Make abutting faces EXACTLY coplanar.** A gusset/rib whose flat side is meant to
  lie flush with a wall face must sit on *exactly* that plane (same coordinate, no
  0.01 mm gap or overlap) — exact coincidence lets OCC merge the faces; a sliver gap
  leaves a seam. Double-check the rib's corner coordinates against the host faces.
- This is worth one or two deliberate attempts when `topo` is the lowest layer and
  everything else is solved — but if `iou` is ALSO low on a part with a diagonal or
  rounded feature, part of that gap is the grader's sampling resolution, not your
  model; don't burn the whole budget chasing the last face.

## Mindset

- **Verifiable reward, so be empirical.** Don't argue with the score; change the
  geometry and re-measure. The harness is ground truth for "closer or not".
- **One clear hypothesis per turn.** "Add the four holes." "Convert inches to mm."
  "Fillet the top four vertical edges r=3." Change that, keep everything that was
  already right, resubmit. Scattershot edits make the signal unreadable.
- **Don't regress.** If the ledger's best beat your current attempt, diff against
  the kept best rather than starting over.
- **Stop when you hit target.** Over-polishing past the target burns budget the
  grid needs for harder tasks.
