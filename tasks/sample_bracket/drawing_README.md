# Drawing track — add `drawing.png` here

The **drawing track** (`--track drawing`) is the hard half of the benchmark: the
agent gets ONLY a 2D engineering drawing image and must derive the full geometry
spec itself before modelling. This is where frontier models fall down — reading
dense dimensions / GD&T off a downsampled raster.

To exercise it on the sample bracket, drop a file named `drawing.png` here — a
dimensioned orthographic drawing of the 80×50×8 plate with the four holes and the
central slot. You can:

- export a drawing/projection from any CAD tool of `ground_truth/result.step`,
- hand-draw and scan one, or
- start from a real benchmark part instead (recommended — see
  `scripts/DATASETS.md` for NIST PMI and SolidWorks Model Mania, which ship real
  drawings + STEP).

Keep the raster **high resolution** (long edge ≥ 2000 px). The whole point of the
drawing track is to measure how much dimension text survives the vision pipeline,
so don't pre-shrink it.

Once `drawing.png` exists, set this task's `default_track` to `drawing` in
`tasks/manifest.yaml`, or pass `--track drawing` on the command line.
