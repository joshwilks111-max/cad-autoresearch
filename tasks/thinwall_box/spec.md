# Thin-Wall Tray — Geometry Spec (spec track)

A human-written specification of design intent. Translate it into a correct
build123d program: pure execution, no drawing-reading.

## Overall
- Units: **millimetres**.
- Outer body: a rectangular box, **80 (X) × 60 (Y) × 30 (Z)** mm, centred on the
  origin in X and Y, with its bottom face on the Z=0 plane (so it occupies
  Z = 0…30).

## Features
1. **Hollow interior (open-top tray)**: the box is shelled to a uniform
   **2 mm wall thickness** on the four side walls and the bottom, leaving the
   **top open**. Equivalently, subtract an inner pocket of
   **76 (X) × 56 (Y)** that starts at **Z = 2** (preserving a 2 mm floor) and
   runs up **through the top face** (so the top is fully open, not capped).
   - Side walls: 2 mm thick all round (inner cavity 76 × 56 centred on origin).
   - Floor: 2 mm thick (cavity starts at Z=2).
   - Top: **open** — no lid.

## Acceptance
- Single solid body, watertight (a tray with a 2 mm floor + 2 mm walls is a
  valid closed shell — the "open top" means no material above the rim, not a
  non-manifold gap).
- Overall bounding box **80 × 60 × 30 mm**.
- Wall thickness **2 mm** uniform; interior cavity **76 × 56 × 28 mm** (open top).

## Notes for the modeller
- Build the solid outer box first, then **subtract** the inner cavity. Make the
  subtracting box tall enough (start at Z=2, extend to ≥ Z=30) so it cleanly
  breaks the top open rather than leaving a thin skin.
- This part deliberately has a **sub-voxel-scale wall** (2 mm) — model the
  geometry exactly; the wall thickness is the point of the part.
- Align the outer box bottom on Z=0 (`align=(Align.CENTER, Align.CENTER, Align.MIN)`);
  offset the cavity up by the 2 mm floor before subtracting.
