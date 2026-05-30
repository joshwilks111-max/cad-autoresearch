# Flanged Bushing — Geometry Spec (spec track)

A clean, fully round (rotationally-symmetric) part: a flanged sleeve bushing with a
stepped inner diameter (counterbore). Translate to build123d.

## Overall
- Units: **millimetres**. Coaxial about the Z axis, base bottom on Z=0.

## Features (all concentric on Z)
1. **Sleeve**: cylinder **radius 15 mm** (Ø30), **total height 40 mm** (Z 0…40).
2. **Base flange**: cylinder **radius 28 mm** (Ø56), **height 6 mm** (Z 0…6),
   concentric with the sleeve at the base.
3. **Through bore**: **radius 9 mm** (Ø18), cut **through the full height**
   (Z 0…40) on the central axis — the bushing inner diameter.
4. **Top counterbore**: **radius 12 mm** (Ø24), **depth 8 mm** (Z 32…40), cut from
   the **top** coaxially — a stepped (larger) inner diameter above the bore.
5. **Chamfers**: **1 mm × 45°** on the **top outer rim of the sleeve** (the Ø30 rim
   at Z=40) and on the **bore mouth at the bottom** (the Ø18 inner edge at Z=0).

## Acceptance
- Single solid body, watertight.
- Bounding box **56 × 56 × 40 mm**.
- The part is rotationally symmetric (the grader uses the rotation-invariant IoU).

## Notes
- The bore is a subtraction through the full sleeve and flange; the counterbore is a
  shallower, wider coaxial subtraction from the top, leaving a Ø18 → Ø24 inner step
  at Z=32.
- Apply the chamfers last: one to the single top outer (r=15, highest) circular edge
  of the sleeve, one to the single bore-mouth (r=9, lowest) circular edge.
