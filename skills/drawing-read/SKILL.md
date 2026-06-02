---
name: drawing-read
description: Read a 2D mechanical ENGINEERING drawing (PNG/JPG/PDF of a part — dimensioned views, not a text document) into a precise, structured geometry spec a modeller can build from without seeing the drawing. Use this whenever a part DRAWING IMAGE is the input and you need the geometry as data — extract every dimension, feature, polarity, and GD&T callout into JSON, with units normalized to mm (the inch→mm trap). Triggers on "read this drawing", "extract dimensions from this drawing / print", "what are the dimensions in this print", "turn this drawing into a spec", a drawing.png handed to a CAD task, or any time someone hands you an engineering print and wants the callouts pulled out. This is the ~40% (Opus) / ~77% (Gemini) bottleneck in AI-to-CAD, so it is isolated from modelling on purpose. Hand the resulting spec to the cad-reconstruct skill to build it. Do NOT use to: model/build a part (that's cad-reconstruct), score or grade a STEP (that's cad-grade), extract text/tables from a document PDF like an invoice or contract (wrong domain — this is for dimensioned part drawings), or merely classify what a drawing depicts without extracting its geometry.
triggers:
  - "read this drawing"
  - "extract dimensions from this drawing"
  - "what are the dimensions in this print"
  - "turn this drawing into a spec"
  - "a drawing.png / drawing image handed to a CAD task"
---

# Drawing read

Turn a 2D engineering drawing into a precise, structured geometry spec — the
**drawing → spec** step of the AI-to-CAD pipeline (`drawing-read → cad-reconstruct
→ cad-grade`, see `docs/skills.md`). You read the print and report what's on it;
you do **not** write CAD code. This is the single hardest open problem in AI-to-CAD
(frontier models reconstruct well from a good spec but misread dense rasters), so
it is a pack of its own — isolate the read so a modelling slip can't corrupt it.

## What it produces
A schema-shaped JSON object: `units`, `views_present`, `dimensions[]`
(`{view, type, nominal_mm, *_tol_mm, feature_ref}`), `features[]`
(`{id, type, polarity, diameter_mm, depth_mm, quantity, gdt_refs}`), `gdt_frames[]`,
and a `title_block`. Every length is recorded as drawn; a normalizer then scales
inch → mm so the downstream modeller always sees millimetres.

## How to run
- Programmatic / one-shot (the scaffold + best-available vision backend):
  ```
  python drawing_extract.py --drawing tasks/<id>/drawing.png --json
  ```
  `--backend auto` routes to Gemini when reachable (the stronger reader, ~77%),
  falling back to Claude (~40%) then a blank scaffold. The result is ALWAYS passed
  through `unit_normalize.normalize_to_mm` so the recurring inch→mm bug is
  architecturally impossible.
- Careful / agentic read: follow `prompts/vision_subagent.md` — a 6-step
  chain-of-thought (views → dimensions → features → GD&T → title block → emit JSON)
  whose ordering materially improves accuracy. Be slow, literal, exhaustive; read
  what is drawn, not what the part "should" be.

## The procedure (never collapse the steps)
1. **Views** — inventory every view (front/top/right/section/iso) + projection +
   scale.
2. **Units** — read the title block; if inch, every value also in mm (×25.4). The
   title block is authoritative — prefer it over guessing from magnitude.
3. **Dimensions** — list EVERY dimension, view by view: value, unit if stated,
   what it measures, tolerance. Diameters (Ø), radii (R), linear, angular, depth.
   Beware spacings-vs-extents (a "90 = 2×45" bolt pitch is not the part width).
4. **Features** — type (hole/boss/slot/fillet/chamfer/thread/pocket/counterbore)
   and POLARITY: a dashed (hidden) circle is a bored hole → `cut`; a solid circle
   on a raised feature is a boss → `add`.
5. **GD&T** — every feature control frame: symbol, tolerance, material condition
   (MMC/LMC/RFS), datums. The weakest area (~50%); record best-read + flag low
   confidence rather than omit.
6. **Title block** — units, scale, material, general-tolerance note, drawing number.

## Quality bar
The benchmark is the offline drawing-read eval at `evals/` (run
`python -m pytest evals/`): it scores an extraction against a hand-authored key on
dimension recall/precision, unit-correctness, and feature count. **Pre-registered
bar: recall ≥ 0.8.** A canary fixture trips on a dropped callout or an inch-misread.
The live extraction path is gated behind `RUN_LLM_EVALS=1`.

## Guardrails
- The drawing is an INPUT, not the answer key — reading it is GT-safe. Never read
  anything under any `ground_truth/` directory.
- Record what is drawn. Do not invent callouts the print doesn't show, and do not
  drop ones it does. Missed dimensions (low recall) break the reconstruction;
  hallucinated ones (low precision) are a different failure — the eval separates them.
- Hand the structured spec to `cad-reconstruct`; do not model here.
