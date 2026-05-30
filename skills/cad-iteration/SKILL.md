---
name: cad-iteration
description: Reconstruct a mechanical part as a build123d program and iterate it against a deterministic geometric grader. Use when given a part to model from a written geometry spec or a 2D engineering drawing, when asked to match/reproduce a reference STEP/STL, or when running the CAD autoresearch loop (propose a build123d candidate, grade it on volume/bbox/IoU/topology/Chamfer, read the feedback, revise). Triggers on "model this part", "reproduce this drawing in CAD", "build123d", "match this STEP", or working inside a cad-autoresearch repo. Do not use for freeform generative/artistic 3D, mesh sculpting, or CAM/toolpathing.
---

# CAD iteration

Model a target part as a **build123d** program, graded by a deterministic
six-layer reward against hidden ground truth, and iterate on the score. This skill
is the worker-side discipline for the `cad-autoresearch` harness; if that repo is
present, its `program.md` is the authoritative manual — read it first.

## The loop
Propose → execute → evaluate → keep/discard. Each turn: read the spec/drawing and
last feedback, write one `candidate.py` defining a module-level `result` solid, let
the harness build + grade it, then read the score breakdown, the targeted hints,
and the rendered views, and change one clear thing.

## Candidate contract
- Define `result` (build123d `BuildPart`/`Part`/`Solid`, or a CadQuery `Workplane`).
- Do **not** export, grade, or orchestrate — the harness sandbox does that.
- Do **not** read anything under any `ground_truth/` directory.
- Self-contained and deterministic; millimetres unless told otherwise.

## Optimise the score in order
1. **body** — get a valid watertight solid that builds at all.
2. **bbox** — nail the overall envelope (sorted extents).
3. **volume** — match total volume (catches polarity errors: a feature that should
   cut must use `Mode.SUBTRACT` / `Hole`, or volume comes back over).
4. **iou** — get the gross shape/proportions right.
5. **topology** — match exact face/edge/vertex counts (every missing fillet,
   chamfer, or hole shows up here).
6. **chamfer** — refine exact radii and feature positions.
Don't polish fillets while the bounding box is still wrong.

## Two tracks
- **spec track**: translate a written spec → build123d. Pure execution; aim for
  composite ≥ ~0.95.
- **drawing track**: you get only an image. Read it FIRST — extract every
  dimension, feature, and GD&T callout into an explicit spec before modelling.
  Reading the drawing is a separate skill from modelling; isolate it (a vision
  subagent) so a modelling slip doesn't corrupt your reading of the print.

## Decompose when it helps
Spawn a vision subagent to read a drawing, or a debugger subagent to fix a build
failure (empty selector, wrong boolean mode, fillet radius too large, inch↔mm
scale). Always converge back to a single `candidate.py`.

## build123d essentials
```python
from build123d import *
with BuildPart() as p:
    Box(80, 50, 8)                          # centred L x W x H
    with Locations((30,0,0),(-30,0,0)):
        Hole(radius=2.5)                    # subtracts a through-hole
    with BuildSketch():
        SlotOverall(30, 8)
    extrude(amount=-8, mode=Mode.SUBTRACT)  # ADD | SUBTRACT | INTERSECT
    fillet(p.edges().filter_by(Axis.Z), radius=3)
result = p
```
Selectors: `.edges()/.faces()`, `.filter_by(Axis.Z | GeomType.CIRCLE)`,
`.group_by(Axis.Z)[-1]`, `.sort_by(...)`. A selector grabbing the wrong entities is
the #1 cause of fillet/chamfer topology errors — inspect a render and narrow it.

## Mindset
Be empirical: the score is truth, so argue with the geometry, not the grader. One
hypothesis per turn, never regress below the kept best, stop at target.
