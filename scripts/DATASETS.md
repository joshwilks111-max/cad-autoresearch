# Datasets — where to get real ground-truth parts

The sample bracket is a toy to prove the pipeline. Real research needs real parts:
a **drawing** (for the drawing track) and a **ground-truth STEP** (for grading).
For each source below, build a task by adding a folder under `tasks/<id>/` with a
`make_ground_truth.py` (or just drop a `ground_truth/result.step` and run a small
script to also emit `result.stl` + `topology.json` + `meta.json`), a `spec.md`,
and optionally a `drawing.png`, then register it in `tasks/manifest.yaml`.

## Parts that ship drawings + solids (best for the drawing track)

- **NIST PMI / MBE test cases.** The NIST MBE PMI Validation and Conformance
  Testing project publishes test-case parts (the "FTC" series) with both annotated
  models and drawings — purpose-built for checking whether tools read GD&T/PMI
  correctly. Ideal hard-track material. Search: "NIST MBE PMI validation test
  cases". (US Government work; check the specific page for terms.)
- **SolidWorks "Model Mania".** Years of challenge parts come with a dimensioned
  drawing and a known solid. Great medium-difficulty drawing-track tasks. Source
  the drawing + model from the official challenge archives.

## Large model corpora (best for the spec track / scale)

- **ABC dataset** — ~1M CAD models with B-rep (STEP) + meshes. Huge, varied.
  Licensing per-model; check the dataset page. Good for sampling many spec-track
  parts programmatically.
- **Fusion 360 Gallery (Reconstruction/Assembly)** — sequences + B-rep solids;
  useful if you want construction-sequence supervision later.
- **DeepCAD** — ~178k models as CAD construction sequences + meshes; widely used
  as a generation/repro benchmark. Good for spec-track evaluation at scale.

## Recent CAD-reconstruction benchmarks (compare your numbers to theirs)

- **Text2CAD / Text2CAD-Bench** — text-prompt → CAD.
- **CADBench / BenchCAD (2025–26)** — graded CAD reconstruction with difficulty
  tiers; mirror their easy/medium/hard banding in `tier:` so results are
  comparable.

## Turning a STEP into a task (recipe)

```python
# tasks/<id>/make_ground_truth.py  (minimal: you already have the STEP)
from pathlib import Path; import json
from build123d import import_step, export_stl
OUT = Path(__file__).resolve().parent / "ground_truth"; OUT.mkdir(exist_ok=True)
solid = import_step(str(OUT / "result.step"))          # you provide result.step
export_stl(solid, str(OUT / "result.stl"), tolerance=0.05)
bb = solid.bounding_box()
(OUT/"meta.json").write_text(json.dumps(
    {"volume": float(abs(solid.volume)),
     "bbox": [bb.size.X, bb.size.Y, bb.size.Z]}))
# topology.json: reuse the OCP face/edge/vertex counter from the sample task
```

## Licensing note
Datasets carry their own licences (research-only, attribution, etc.). Keep parts
you redistribute compatible with your use, and never commit data you don't have
the right to share. Ground-truth folders are local-only by default — they're not
in `.gitignore` so you *can* keep them, but check the licence before pushing.
