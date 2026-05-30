"""
candidate.py -- NIST CTC-05 reconstruction (SPEC track). NOT a rectangular block (the
survey was wrong) -- it is a large COAXIAL STEPPED TURNING (a tiered lathe shaft):
Ø558.8 base flange -> conical shoulder -> Ø304.8 tower -> conical skirt -> Ø63.5
spindle, with a Ø254 central bore open at the bottom and 10 counterbored bolt holes
on the base flange. Measured from the GT cross-sections (parallel-runner V).

Strategy: revolve ONE outer (r,z) profile 360 about Z (captures flange+cones+tower+
spindle in one watertight solid, avoiding a long fragile boolean union chain), then
subtract the central bore and the bolt-circle holes. Units: mm; axis = Z, base at z=0.
"""
from build123d import (BuildPart, BuildSketch, BuildLine, Polyline, Plane, Axis,
                       make_face, revolve, Cylinder, Locations, PolarLocations,
                       Align, Mode)
import math

# Outer radial profile (r, z), base -> top. Cones are straight segments between steps.
# flange Ø558.8 (r279.4) z0..25.4; shoulder cone to r152.4 by z55; tower r152.4 to
# z124; skirt cone to r31.75 by z280; spindle r31.75 to z476; top chamfer to r25 at 482.6.
PROFILE = [
    (0, 0), (279.4, 0), (279.4, 25.4),
    (272.0, 25.4),               # flange top outer (slight step in before the shoulder)
    (152.4, 55.0),               # shoulder cone down to tower radius
    (152.4, 124.0),              # tower (constant r for 70mm)
    (31.75, 280.0),              # skirt cone down to spindle radius
    (31.75, 476.0),              # spindle (constant r, 196mm tall)
    (25.0, 482.6),               # top chamfer
    (0, 482.6),
]

with BuildPart() as p:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*PROFILE, close=True)
        make_face()
    revolve(axis=Axis.Z)

    # central bore Ø254 (r127), open at the bottom, depth ~124mm
    with Locations((0, 0, 62.0)):
        Cylinder(radius=127.0, height=124.0, mode=Mode.SUBTRACT)

    # 10 counterbored bolt holes on bolt circle R=222.2, every 30deg except 0 and 180.
    # PolarLocations places at angles 0,36,... so use explicit angles instead.
    angles = [30, 60, 90, 120, 150, 210, 240, 270, 300, 330]
    for a in angles:
        cx = 222.2 * math.cos(math.radians(a))
        cy = 222.2 * math.sin(math.radians(a))
        with Locations((cx, cy, 12.7)):
            Cylinder(radius=9.5, height=25.4, mode=Mode.SUBTRACT)     # Ø19 pilot
        with Locations((cx, cy, 19.2)):
            Cylinder(radius=19.0, height=12.4, mode=Mode.SUBTRACT)    # Ø38 counterbore

    # 4 small Ø8 holes at 0 and 180deg, two radii
    for (rx, a) in [(203.2, 0), (234.9, 0), (203.2, 180), (234.9, 180)]:
        cx = rx * math.cos(math.radians(a))
        cy = rx * math.sin(math.radians(a))
        with Locations((cx, cy, 20.0)):
            Cylinder(radius=4.0, height=40.0, mode=Mode.SUBTRACT)

result = p
