# Slotted Ring — Geometry Spec (spec track)

A castle-nut-style slotted collar: a near-round annular ring with a ring of axial
slots cut into the top face. Translate to build123d.

## Overall
- Units: **millimetres**. Coaxial about the Z axis, base bottom on Z=0.

## Features (all concentric on / patterned about Z)
1. **Collar (annular ring)**: outer **radius 25 mm** (Ø50), central bore
   **radius 14 mm** (Ø28), **height 18 mm** (Z 0…18). Wall thickness 11 mm.
2. **Slots**: **6** rectangular slots cut into the **top face**, evenly spaced at
   **60°** (a polar pattern about the Z axis). Each slot is **5 mm wide**
   (tangential), **8 mm deep** (cut Z 10…18, measured down from the top), and spans
   the **full radial wall thickness** (it breaches both the inner bore wall and the
   outer wall, leaving a square-bottomed notch open to the bore and to the outside).
3. **Chamfer**: **1 mm × 45°** on the **top outer edge** (the Ø50 rim at Z=18). After
   the slots are cut, that rim is six separate arcs — chamfer all of them.

## Acceptance
- Single solid body, watertight.
- Bounding box **50 × 50 × 18 mm**.
- The collar dominates the mass, so the part still reads as rotationally symmetric to
  the grader (the rotation-invariant cylindrical IoU is used). The 6 slots are the
  feature that distinguishes a correct reconstruction from a plain bored collar.

## Notes
- The bore is a through-hole on the central axis (Ø28, full height).
- A clean construction: build the annular collar (outer cylinder minus bore), then
  subtract a 60°-spaced polar pattern of 6 box cutters from the top face, then apply
  the rim chamfer last.
- Each slot cutter must be long enough radially to clear both walls (so the slot
  floor is flat across the full 11 mm wall and the slot opens to bore and exterior).
