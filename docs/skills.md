# Skill packs

This repo's capabilities are packaged as **three skill packs** under `skills/`. They
are deliberately separate (MECE): each owns one stage of the AI-to-CAD pipeline, with
its own `SKILL.md`, its own tools, and its own eval. They compose left-to-right:

```
   a 2D drawing                a written spec               a finished part
        │                            │                            │
        ▼                            ▼                            ▼
  ┌─────────────┐  spec     ┌──────────────────┐  STEP/   ┌─────────────┐
  │ drawing-read │ ───────▶ │  cad-reconstruct  │ ──────▶ │  cad-grade   │
  │  image→spec  │          │   spec→build123d   │ cand    │ part→score   │
  └─────────────┘          └──────────────────┘          └─────────────┘
```

| Pack | Stage | Reads | Produces | Tools it wraps | Eval / bar |
|------|-------|-------|----------|----------------|------------|
| **drawing-read** | image → spec | a drawing PNG/JPG/PDF (an input) | structured JSON spec (dims, features, GD&T), units in mm | `drawing_extract.py`, `unit_normalize.py`, `prompts/vision_subagent.md` | `evals/` offline drawing-read eval; recall ≥ 0.8 |
| **cad-reconstruct** | spec → model | a written spec (or STEP/STL to match) | a `build123d` program (`candidate.py` → `result`) | the propose→grade→revise loop, `program.md`, `run_inner_loop.py` | the loop's composite ≥ ~0.95 + `tests/` |
| **cad-grade** | model → score | a STEP or a build123d candidate + a reference | a composite + per-layer scores (body/bbox/volume/IoU/topology/chamfer) | `timetrial/grade_step.py`, `grade_one.py`, the `harness/reward.py` layers | `tests/test_reward.py` (the referee's own tests) |

## Why three packs

- **Isolation is correctness, not tidiness.** Reading a dense drawing is the ~40%
  (Opus) / ~77% (Gemini) bottleneck; modelling from a clean spec is near-solved. If
  they were one pack a modelling slip would masquerade as a misread print, and the
  grader could drift toward the modeller. Splitting them keeps each honest.
- **They multiply.** Each pack is independently usable — grade any STEP without
  modelling it, read any drawing without building it, model any spec without a
  drawing. The pipeline is just the common composition.
- **Each carries its own eval**, so "does it work" is answerable per pack: the
  drawing-read eval lands in `drawing-read`, the geometry referee's tests in
  `cad-grade`, the loop's end-to-end tests in `cad-reconstruct`.

## Running them

```bash
# read a drawing into a spec (offline scaffold + best vision backend)
python drawing_extract.py --drawing tasks/<id>/drawing.png --json

# reconstruct from a spec, graded each turn (offline mock, or real claude proposer)
python run_inner_loop.py --task <id> --proposer mock --budget 5
python run_inner_loop.py --task <id> --proposer claude --model opus --budget 30

# grade a finished STEP against a reference
python timetrial/grade_step.py --task <id> --step part.step --json

# the packs' evals
python -m pytest evals/   # drawing-read eval (offline, free)
python -m pytest tests/   # referee + loop tests
```

See each pack's `skills/<name>/SKILL.md` for the full discipline, and
`docs/ARCHITECTURE.md` / `docs/known-limitations.md` for the harness internals.
