# Twin Bodies — Geometry Spec (spec track)

A human-written specification of design intent. Translate it into a correct
build123d program: pure execution, no drawing-reading.

## Overall
- Units: **millimetres**.
- This part is **two identical disjoint solid boxes** (a multi-body part — they
  do not touch).

## Features
1. **Box A**: a solid box **30 (X) × 30 (Y) × 20 (Z)** mm, with its bottom face
   on Z=0, centred in X/Y at **(X, Y) = (−40, 0)** (so it occupies
   X = −55…−25, Y = −15…+15, Z = 0…20).
2. **Box B**: an identical solid box **30 × 30 × 20** mm, bottom on Z=0, centred
   at **(X, Y) = (+40, 0)** (X = +25…+55, Y = −15…+15, Z = 0…20).

The two boxes are **80 mm apart centre-to-centre** and **symmetric about the
origin**. There is a 50 mm clear gap between their near faces (−25 to +25 in X).

## Acceptance
- **Two disjoint solid bodies** in one compound/part (NOT fused, NOT touching).
- Overall bounding box **110 (X) × 30 (Y) × 20 (Z)** mm (spanning both boxes plus
  the gap).
- Each box volume = 18 000 mm³; total volume = 36 000 mm³.

## Notes for the modeller
- Place both boxes in a single `BuildPart` using two `Locations`/`Locations` at
  (−40, 0, 0) and (+40, 0, 0), each `Box(30, 30, 20,
  align=(Align.CENTER, Align.CENTER, Align.MIN))`.
- Do **not** fuse or bridge them — the part is intentionally two separate solids
  (this exercises the pose-invariant IoU on disjoint bodies).
