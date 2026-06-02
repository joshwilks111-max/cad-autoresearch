---
name: cad-reconstruct
description: Reconstruct a mechanical part as a build123d program and iterate it against a deterministic geometric grader (the propose → build → grade → revise loop). Use when given a written geometry spec to model, when asked to match/reproduce a reference STEP/STL, or when running the CAD autoresearch loop (propose a build123d candidate, grade it on volume/bbox/IoU/topology/Chamfer, read the feedback, revise). Triggers on "model this part", "build123d", "match this STEP", "reconstruct this part", or working inside a cad-autoresearch repo. If the input is a 2D drawing image, read it into a spec first with the drawing-read skill, then use this. To score a finished STEP against a reference, use the cad-grade skill. Do not use for freeform generative/artistic 3D, mesh sculpting, or CAM/toolpathing.
---

# CAD reconstruct

Model a target part as a **build123d** program, graded by a deterministic
multi-layer reward against hidden ground truth, and iterate on the score. This is
the modelling loop of the `cad-autoresearch` harness; if that repo is present, its
`program.md` is the authoritative manual — read it first.

This pack is one of three that compose into the AI-to-CAD pipeline
(`drawing-read → cad-reconstruct → cad-grade`, see `docs/skills.md`). It owns the
**spec → model** step. Reading a drawing into a spec is a *different* skill
(`drawing-read`); scoring a finished STEP against a reference is a *different* skill
(`cad-grade`). Keeping them separate is deliberate — a modelling slip must not
corrupt how the drawing was read, and the grader must stay independent of the modeller.

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

## Input is a spec, not a drawing
This pack models from a **written spec**. If you were handed a 2D drawing image,
that is the `drawing-read` pack's job: run it first to extract every dimension,
feature, and GD&T callout into an explicit spec (with units normalized to mm),
then model from that spec here. Don't read the raster and model in the same breath
— a modelling slip would then masquerade as a misread print.

## Decompose when it helps
Spawn a debugger subagent to fix a build failure (empty selector, wrong boolean
mode, fillet radius too large). For drawing-reading specifically, delegate to the
`drawing-read` pack rather than reading inline. Always converge back to a single
`candidate.py`.

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
