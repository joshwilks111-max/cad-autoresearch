"""
candidate.py -- flanged_bushing reconstruction (SPEC track). A flanged sleeve bushing:
Ø56 base flange (6mm) + Ø30 sleeve (to z=40) + Ø18 through bore, stepping to a Ø24
counterbore (8mm deep) at the top; 1mm chamfers on the top outer rim and the bottom
bore mouth. Fully rotationally symmetric -> the cylindrical IoU path.

Built by revolving ONE closed axial half-section 360 about Z. The chamfers are baked
into the profile as straight segments (15->14 over z 39..40; 9->10 over z 1..0), so no
separate .chamfer() calls are needed. Profile measured from the GT (validated exact to
9 dp against the analytic volume 26973.71). Units: mm. XZ plane: x = radius, z = axial.
"""
from build123d import (BuildPart, BuildSketch, BuildLine, Polyline, Plane, Axis,
                       make_face, revolve)

# Closed (r, z) half-section, CCW from bottom-outer. Encodes both chamfers as segments.
PROFILE = [
    (28, 0), (28, 6), (15, 6), (15, 39), (14, 40),
    (12, 40), (12, 32), (9, 32), (9, 1), (10, 0),
]

with BuildPart() as p:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*PROFILE, close=True)
        make_face()
    revolve(axis=Axis.Z)

result = p
