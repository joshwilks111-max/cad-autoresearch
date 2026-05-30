"""
candidate.py — stepped_hub reconstruction (SPEC track). A clean round part:
coaxial about Z, base bottom on Z=0.
  - Base flange: cylinder r30 (Ø60), h8 (Z 0..8).
  - Hub: cylinder r18 (Ø36), h18, on the flange (Z 8..26).
  - Axial bore: r8 (Ø16), through the full height (Z 0..26).
  - 2 mm chamfer on the top outer edge of the hub (Ø36 rim at Z=26).
Module-level `result`. Units: mm.
"""

from build123d import (BuildPart, Cylinder, Locations, Align, Axis, GeomType,
                       Mode, chamfer)

with BuildPart() as p:
    Cylinder(radius=30, height=8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((0, 0, 8)):
        Cylinder(radius=18, height=18, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((0, 0, 26)):
        Cylinder(radius=8, height=26, align=(Align.CENTER, Align.CENTER, Align.MAX),
                 mode=Mode.SUBTRACT)
    top_outer = (p.edges().filter_by(GeomType.CIRCLE)
                 .group_by(Axis.Z)[-1]
                 .sort_by(lambda e: e.radius)[-1:])
    chamfer(top_outer, length=2)

result = p
