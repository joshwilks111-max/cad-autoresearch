# V-Groove Pulley — Geometry Spec (spec track)

A clean, fully round (rotationally-symmetric) V-belt pulley. Translate to build123d.

## Overall
- Units: **millimetres**. Coaxial about the **Z axis**, symmetric about the
  **mid-plane Z = 0** (faces sit at equal +Z and -Z offsets).

## Features (all concentric on Z)
1. **Pulley disc**: outer radius **40 mm** (Ø80), total width **20 mm**
   (Z −10…+10).
2. **V-groove** around the outer rim (OD): a **40° included-angle** vee cut into the
   OD, **centered on the mid-plane**, **12 mm deep** → groove **root radius 28 mm**
   (Ø56). The vee mouth at the OD opens to ±(12·tan20°) ≈ ±4.37 mm about Z = 0.
3. **Hub** (raised boss): radius **20 mm** (Ø40), extending **6 mm beyond each
   face** → hub width **32 mm** (Z −16…+16), concentric.
4. **Central bore**: radius **10 mm** (Ø20), through the **full hub width**, on the
   central axis.
5. **Chamfer**: **1 mm** on **both bore mouths** (the two Ø20 circular edges on the
   hub faces).

## Acceptance
- Single solid body, watertight.
- Bounding box **80 × 80 × 32 mm**.
- The part is rotationally symmetric (the grader uses the rotation-invariant IoU).

## Notes
- Easiest construction: revolve the (radius, axial) half cross-section 360° about Z
  — the disc faces, the OD walls, the vee notch, and the hub steps are all one
  closed profile — then subtract the central bore and chamfer the bore mouths.
- The vee is symmetric about Z = 0; the disc and hub are likewise symmetric about
  Z = 0, so the part reads the same from +Z and −Z.
