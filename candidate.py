"""
candidate.py — motor_mount reconstruction (SPEC track).

Translated directly from tasks/motor_mount/spec.md. Units: millimetres.

Geometry:
  - Base plate 100 (X) x 70 (Y) x 10 (Z), centred in XY, bottom on Z=0.
  - Central hub: cylinder r=20, h=25, base on Z=10 (top at Z=35), coaxial with Z.
  - Axial bore: r=8 through the full height (Z=0..35), centred.
  - 4 mounting holes r=2.5 through the plate at (+/-40, +/-25).
  - 2 mm chamfer on the top circular edge of the hub.

Module-level `result` is the final solid (required). No export/grade here.
"""

from build123d import (
    BuildPart, Box, Cylinder, Hole, Locations, GridLocations,
    chamfer, Align, Axis, Mode, GeomType,
)

with BuildPart() as p:
    # Base plate, bottom on Z=0.
    Box(100, 70, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Central hub rising from the plate top.
    with Locations((0, 0, 10)):
        Cylinder(radius=20, height=25, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Axial bore through hub + plate (full height), cut from the top down.
    with Locations((0, 0, 35)):
        Cylinder(radius=8, height=35, align=(Align.CENTER, Align.CENTER, Align.MAX),
                 mode=Mode.SUBTRACT)

    # Four mounting holes through the plate (batched 2x2 pattern, 80 x 50 spacing).
    with Locations((0, 0, 10)):
        with GridLocations(80, 50, 2, 2):
            Hole(radius=2.5)

    # Chamfer the top circular edge of the hub (highest circular edge), applied last.
    top_circle = p.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1]
    chamfer(top_circle, length=2)

result = p
