# NIST FTC-09 — Geometry Spec (spec track)

A thin, flat **perforated plate** with many through-holes. Real NIST MBE PMI test
case (US Government work, unrestricted). Translate to build123d.

This spec was authored from **measuring the part** (mesh sectioning of the released
solid — the digital equivalent of reading the drawing with calipers), NOT from the
answer-key build program. Never read `ground_truth/`.

## Overall
- Units: **millimetres**.
- A flat rectangular plate lying in a plane, **3.04 mm thick**.
- Plate footprint (the two large in-plane extents): **190.5 mm x 279.4 mm**.
- Overall bounding box therefore ~**190.5 x 279.4 x 3.04 mm**.
- Model the plate in the **XY plane**, thickness along **Z** (Z 0..3.04). The hole
  coordinates below are given as **(x, y)** in the plate plane, centred on the
  part's own origin (x roughly -105..+135, y roughly -83..+84 — the pattern is **not**
  symmetric about the origin, so place holes at the exact coordinates given).
- Volume of the finished (perforated) part ~ **138 660 mm^3**.

## Plate
A solid plate, footprint 190.5 x 279.4, thickness 3.04. Size the plate so every listed
hole falls on it.

## Through-holes (all cut fully through the 3.04 mm thickness)

**29 round holes.** Diameters fall on standard drill sizes; group them as:

- **d = 3.96 mm (r 1.98)** — 7 holes
- **d = 5.62 mm (r 2.81)** — 2 holes
- **d = 5.94 mm (r 2.97)** — 4 holes
- **d = 6.34 mm (r 3.17)** — 10 holes (the dominant size)
- **d = 7.14 mm (r 3.57)** — 3 holes
- **d = 8.00 mm (r 4.00)** — 2 holes
- **d = 19.04 mm (r 9.52)** — 1 hole

Hole centres (x, y) in mm, in the plate plane. For scoring, the count, positions, and
the size distribution are what matter:

```
(-85.68, 30.87)  (-51.39, -58.03) (-51.39, -38.98) (-85.68, -47.87)
(-85.68, -28.82) (-85.68, -66.92) (135.30, 18.17)  (135.30, -19.93)
(135.30, -0.88)  (107.36, 56.27)  (-32.64, 56.27)  (5.76, 84.21)
(107.36, -0.73)  (-32.64, -0.73)  (24.81, 84.21)   (-13.29, 84.21)
(113.71, -83.43) (-102.19, 81.67) (113.71, 81.67)  (-102.19, -83.43)
(-85.68, 49.92)  (-85.68, 11.82)  (-104.73, 16.90) (12.81, -71.44)
(-6.94, -79.62)  (-104.73, 6.74)  (-104.73, 44.84) (-104.73, 55.00)
(21.00, -51.68)
```

The single large **d = 19.04 mm** hole sits at a corner-region coordinate from the list.

**1 large window cutout** — a roughly rectangular through-opening, equivalent radius
~36.8 mm (area ~ 4250 mm^2), centred near **(57, 30)**. Model as a rectangular pocket
(through-cut), ~65 x 65 mm or sized to that area, with lightly rounded corners.

**4 slots / obround cutouts** (through), near y ~ -48 to -52:
- obround eq-r 10.5 near (56.6, -48.5)
- obround eq-r 7.0 near (101.0, -48.5)
- obround eq-r 7.0 near (82.0, -48.5)
- rounded slot eq-r 5.3 near (-8.2, -51.7)

These four are lower priority than the 29 round holes + the window (they carry less of
the topology/volume score), but include them for a faithful reconstruction.

## Acceptance
- Single solid body, watertight, thickness 3.04 mm.
- Bounding box ~190.5 x 279.4 x 3.04 mm.
- The 29 round holes placed at the listed centres with the listed size distribution;
  the large window cut; ideally the 4 slots.
- The dominant score drivers are **volume** (holes remove ~17% vs a solid plate) and
  **topology / IoU** (each hole adds faces/edges and removes interior volume). Surface
  metrics (chamfer / SIoU) are nearly blind to the holes, so getting the holes right is
  what lifts the composite off the ~0.26 bare-plate baseline.

## Notes
- Build the plate, then subtract all holes/cutouts in one pass (e.g. a `Locations` /
  per-centre loop of `Hole`/cylinder subtractions, plus the window and slots), so the
  booleans stay simple and watertight.
- Source / license: NIST MBE PMI Validation & Conformance test case FTC-09,
  https://pages.nist.gov/CAD-PMI-Testing/ — US Government work, unrestricted.
