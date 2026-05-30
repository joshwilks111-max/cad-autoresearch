# Motor Mount Plate — Geometry Spec (spec track)

A human-written specification of design intent. Translate it into a correct
build123d program: pure execution, no drawing-reading.

## Overall
- Units: **millimetres**.
- Base plate: rectangular, **100 (X) × 70 (Y) × 10 (Z)** mm, centred on the origin
  in X and Y, with its bottom face on the Z=0 plane (so it occupies Z = 0…10).

## Features
1. **Central hub**: a solid cylinder, **radius 20 mm**, **height 25 mm**, rising
   from the top face of the plate (its base on Z=10, top at Z=35), coaxial with the
   plate centre (axis = Z through the origin).
2. **Axial bore**: a **radius 8 mm** hole on the central axis, cut **through the
   full height** of the part — through both the hub and the plate (Z = 0…35).
3. **Four mounting holes**: through the plate, **radius 2.5 mm**, on a rectangular
   pattern at (X, Y) = (−40, −25), (+40, −25), (−40, +25), (+40, +25).
4. **Hub top chamfer**: a **2 mm** chamfer on the **top circular edge of the hub**
   (the outer rim of the hub's top face, at Z=35).

## Acceptance
- Single solid body, watertight.
- Overall bounding box **100 × 70 × 35 mm**.
- Volume ≈ 93 240 mm³ (informative; the grader applies its own tolerance).

## Notes for the modeller
- Cut features (the axial bore, the four mounting holes) are **subtractions** —
  watch polarity.
- The chamfer is the **last** operation; apply it to the single top circular edge
  of the hub (e.g. the highest circular edge: `filter_by(GeomType.CIRCLE)` then
  `group_by(Axis.Z)[-1]`).
