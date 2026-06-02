# CAD Autoresearch Skill Resolver

The dispatcher for this repo's three skill packs. Skills are the implementation;
**read the matched skill file before acting.** The packs are MECE (each trigger
routes to exactly one pack) and chain left-to-right:
`drawing-read → cad-reconstruct → cad-grade` (see `docs/skills.md`).

## Read a drawing → spec

| Trigger | Skill |
|---------|-------|
| "read this drawing", "extract dimensions from this drawing", "what are the dimensions in this print", "turn this drawing into a spec", a `drawing.png` handed to a CAD task | `skills/drawing-read/SKILL.md` |

## Reconstruct a part (spec → build123d)

| Trigger | Skill |
|---------|-------|
| "model this part", "reconstruct this part", "build123d", "match this STEP", "match this STL", a written geometry spec to model, running the autoresearch propose→grade→revise loop | `cad-reconstruct` (`skills/cad-reconstruct/SKILL.md`) |

## Grade a part (model → score)

| Trigger | Skill |
|---------|-------|
| "grade this STEP", "score this part against the reference", "how close is this to the target", "is this reconstruction correct", running the time-trial referee | `skills/cad-grade/SKILL.md` |

## Boundaries (what keeps them MECE)

- A **drawing image** in hand → `drawing-read` (never model the raster directly).
- A **written spec** (or a STEP/STL to match) in hand → `cad-reconstruct`.
- A **finished part** + a reference to score against → `cad-grade`.
- Reading is GT-safe; grading is grader-side (its output reveals the reference, never
  feed it into a worker's drawing-track spec).
- None of these handle freeform/artistic 3D, mesh sculpting, or CAM/toolpathing.
