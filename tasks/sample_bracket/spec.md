# Sample Bracket — Geometry Spec (spec track)

A **human-written specification** of design intent — the "good spec" input that, in
the literature, lets an agent reach near-perfect scores. The agent's job is to
translate it into a correct build123d program: pure execution, no drawing-reading.

> Use this file as the input for `--track spec`. For `--track drawing`, the agent
> instead gets `drawing.png` and must derive all of this itself.

## Overall
- Units: **millimetres**.
- Base plate: rectangular, **80 (X) × 50 (Y) × 8 (Z)** mm, centred on the origin.

## Features
1. **Four mounting holes**, through-all, **radius 2.5 mm** (M5 clearance).
   Centres at (X, Y): (−30, −18), (+30, −18), (−30, +18), (+30, +18).
2. **Central slot**, cut **through the full 8 mm thickness**. Overall slot length
   **30 mm** along X, slot width **8 mm** along Y, centred on the origin (an
   "overall length" slot: two R4 semicircular ends capping a 22 mm straight
   section — but specify it as overall 30 × 8).

## Acceptance
- Single solid body, watertight.
- Volume ≈ 30 466.6 mm³ (informative; the grader applies its own tolerance).
- Bounding box exactly 80 × 50 × 8 mm.

## Notes for the modeller
- Cut features (holes, slot) are **subtractions** — watch polarity.
- The slot is a sketch extruded in **−Z** with `Mode.SUBTRACT`, or any equivalent
  that removes material cleanly through the plate.
