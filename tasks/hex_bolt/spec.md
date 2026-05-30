# Hex-Head Shoulder Bolt — Geometry Spec (spec track)

A MIXED prismatic + round part: a hexagonal head on a round cylindrical shank.
Translate to build123d.

## Overall
- Units: **millimetres**. Coaxial about the Z axis, head bottom on Z=0.
- Single watertight solid body.

## Features (all concentric on Z)
1. **Hex head**: a **regular hexagon** with **across-flats 24 mm** (i.e. the distance
   between two opposite flat faces is 24 mm; equivalently the circumradius — centre to
   a corner — is 24/√3 = **13.856 mm**, and the across-corners distance is 27.71 mm),
   extruded **10 mm** tall (**Z 0…10**).
2. **Shank**: a **cylinder radius 8 mm** (Ø16), length **40 mm**, sitting on top of the
   head and coaxial with it (**Z 10…50**).
3. **Shank-tip chamfer**: a **1 mm × 45°** chamfer on the **top edge of the shank** —
   the circular Ø16 rim at **Z = 50**.
4. **Head-edge chamfer**: a small **0.8 mm × 30°** chamfer around the **top outer edge
   of the hex head** (the six straight hexagon edges at the head/shank junction plane,
   **Z = 10**).

## Acceptance
- Single solid body, watertight.
- Bounding box **27.71 × 24.0 × 50.0 mm** (across-corners × across-flats × total height).
- Total volume ≈ **12 988 mm³**.

## Notes
- The hex head is prismatic (flat faces) while the shank is round — orientation of the
  hexagon about Z is free (any 60° rotation is the same part), but keep the flats
  symmetric about the axes if you want the bbox to read 27.71 × 24.0.
- Apply the shank-tip chamfer to the single highest, largest-radius circular edge
  (the Ø16 rim at the very top).
- The head-edge chamfer is optional flavour; it bevels the six top edges of the hex
  head where it meets the shank base plane.
