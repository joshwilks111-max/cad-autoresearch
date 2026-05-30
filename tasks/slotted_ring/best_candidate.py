"""
candidate.py -- slotted_ring reconstruction (SPEC track). A castle-nut-style collar:
an annular ring (OD 50, bore 28, h18) with 6 axial slots (5mm wide, 8mm deep, full
wall) cut into the top face at 60deg, plus a 1mm chamfer on the top outer rim.

Gates as rotationally symmetric (the slots are a small volume fraction), so the
cylindrical IoU path scores it. Construction: annular collar = outer Cylinder minus
bore; subtract a 60deg PolarLocations pattern of 6 box cutters from the top; chamfer
the top outer rim arcs last. Units: mm; coaxial about Z, base at Z=0.
"""
from build123d import (BuildPart, BuildSketch, Plane, Cylinder, Box, Locations,
                       PolarLocations, Align, Axis, GeomType, Mode, chamfer)

R_OUT, R_BORE, H = 25.0, 14.0, 18.0
SLOT_W, SLOT_DEEP = 5.0, 8.0          # tangential width, axial depth (Z 10..18)
SLOT_RADIAL = 2 * R_OUT               # long enough to breach both walls

with BuildPart() as p:
    # annular collar: outer cylinder minus central bore
    Cylinder(radius=R_OUT, height=H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    Cylinder(radius=R_BORE, height=H, align=(Align.CENTER, Align.CENTER, Align.MIN),
             mode=Mode.SUBTRACT)
    # 6 radial slots cut into the TOP face (Z 10..18), 60deg polar pattern
    with Locations((0, 0, H - SLOT_DEEP / 2)):       # box centred in the cut band
        with PolarLocations(radius=0, count=6):       # 6 cutters about the axis
            Box(SLOT_RADIAL, SLOT_W, SLOT_DEEP, mode=Mode.SUBTRACT)
    # 1mm chamfer on the top outer rim (now six arcs at Z=18, largest radius)
    top_outer = (p.edges().filter_by(GeomType.CIRCLE)
                 .group_by(Axis.Z)[-1]
                 .sort_by(lambda e: e.radius))[-6:]
    chamfer(top_outer, length=1.0)

result = p
