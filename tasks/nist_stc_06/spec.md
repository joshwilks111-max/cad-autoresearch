# NIST STC-06 — DRAWING TRACK (no written spec by design)

This is a **drawing-track** task. There is intentionally **no human-authored
geometry spec** here: the input is the engineering drawing (`drawing.png`,
rasterised from NIST's `STC_06.pdf`), and reading it — every dimension, hole,
counterbore, boss, pocket, and GD&T callout — is the task.

Hand-authoring a spec for this ~144-face toleranced part would amount to
reverse-engineering the answer key, which defeats the purpose of the hard track.

- **Run it as:** `--track drawing` (the default for this task).
- **Input:** `drawing.png` (the NIST STC-06 ASME-1 drawing).
- **Ground truth:** built from `nist_stc_06_asme1_ap242-e3.stp` (AP242) by
  `make_ground_truth.py`. Never read `ground_truth/`.
- **Units:** millimetres. Overall bbox is ~247.65 × 304.80 × 127.89 mm.
- **Source / license:** NIST MBE PMI Validation & Conformance test case STC-06,
  https://pages.nist.gov/CAD-PMI-Testing/ — US Government work, unrestricted.

If you ever want a *spec-track* NIST part to hand-author from scratch, start with a
simpler case (e.g. CTC-01) rather than this one.
