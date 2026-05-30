"""
candidate.py — sample_bracket reconstruction (SPEC track).

Translated directly from tasks/sample_bracket/spec.md. Units: millimetres.

Geometry:
  - Base plate: 80 (X) x 50 (Y) x 8 (Z), centred on the origin.
  - Four M5-clearance through-holes, radius 2.5, at (+/-30, +/-18).
  - Central slot, overall 30 (X) x 8 (Y), cut through the full 8 mm thickness,
    centred on the origin (R4 semicircular ends + 22 mm straight section).

The module-level variable `result` is the final solid (required by the harness).
No export / grading here — the sandbox epilogue handles that.
"""

from build123d import (
    BuildPart,
    BuildSketch,
    Box,
    Hole,
    Locations,
    SlotOverall,
    extrude,
    Mode,
)

with BuildPart() as p:
    # Base plate: length(X) x width(Y) x height(Z), centred on origin.
    Box(80, 50, 8)

    # Four mounting holes (through-all). Hole() subtracts by default, boring
    # along the workplane normal through the full plate thickness.
    with Locations((-30, -18, 0), (30, -18, 0), (-30, 18, 0), (30, 18, 0)):
        Hole(radius=2.5)

    # Central slot: overall 30 x 8 (R4 ends), cut clean through the 8 mm plate.
    # SlotOverall(width=overall length=30, height=transverse width=8).
    with BuildSketch():
        SlotOverall(30, 8)
    extrude(amount=-8, mode=Mode.SUBTRACT)

result = p
