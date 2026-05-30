# Stepped Hub — Geometry Spec (spec track)

A clean, fully round (rotationally-symmetric) part. Translate to build123d.

## Overall
- Units: **millimetres**. Coaxial about the Z axis, base bottom on Z=0.

## Features (all concentric on Z)
1. **Base flange**: cylinder **radius 30 mm** (Ø60), **height 8 mm** (Z 0…8).
2. **Hub**: cylinder **radius 18 mm** (Ø36), **height 18 mm**, on top of the flange
   (Z 8…26).
3. **Axial bore**: **radius 8 mm** (Ø16), cut **through the full height** (Z 0…26),
   on the central axis.
4. **Chamfer**: **2 mm** on the **top outer edge of the hub** (the Ø36 rim at Z=26).

## Acceptance
- Single solid body, watertight.
- Bounding box **60 × 60 × 26 mm**.
- The part is rotationally symmetric (the grader uses the rotation-invariant IoU).

## Notes
- The bore is a subtraction through both the hub and the flange.
- Apply the chamfer last, to the single top outer (largest-radius, highest) circular
  edge of the hub.
