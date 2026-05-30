# NIST FTC-11 — DRAWING TRACK (stub spec)

This is a **drawing-track** task. The primary input is the engineering drawing
(`drawing.png`), and reading it is the agent's job.

- **Run it as:** `--track drawing` (the default for this task).
- **Ground truth:** built from `nist_ftc_11_asme1_rb.stp` (AP203) by
  `make_ground_truth.py`. Never read `ground_truth/`.
- **Units:** millimetres. Overall bbox is ~63 × 63 × 3 mm.
- **Face count:** 6 (the simplest NIST part — a flat square plate/washer).
- **Source / license:** NIST MBE PMI Validation & Conformance test case FTC-11,
  https://pages.nist.gov/CAD-PMI-Testing/ — US Government work, unrestricted.

## Rough geometry hint (from probe, NOT from ground_truth/)

A 63 mm × 63 mm × 3 mm flat square plate, 6 faces, 1 solid, 1 shell.
Volume ≈ 5129 mm³.  Euler characteristic = 2 (simple convex solid).

If the task were on the spec track, the candidate would be approximately:

```python
from build123d import Box
result = Box(63, 63, 3)
```

But the drawing may reveal holes, chamfers, or other features — read drawing.png
before assuming it is a bare box.
