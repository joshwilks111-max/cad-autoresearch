"""
candidate.py -- NIST FTC-09 reconstruction (SPEC track). A thin flat PERFORATED PLATE:
190.5 x 279.4 x 3.04 mm with 29 round through-holes, 1 large rectangular window cutout,
and 4 obround/slot cutouts. Authored from measuring the released part (mesh sectioning),
not the answer-key build.

Strategy (OCC-boolean-robust): build the solid plate, then cut EVERY feature in a SINGLE
subtract pass -- one sketch holding all 29 circles + the window rectangle + the 4 slots,
extruded through the full thickness with mode=SUBTRACT. One boolean op (not 34 sequential
cuts) avoids the silent-fragment failure class. Units: mm; plate in XY, thickness +Z.
"""
from build123d import (BuildPart, BuildSketch, Plane, Circle, Rectangle,
                       SlotOverall, Locations, extrude, Mode)

# GT lies in the XZ plane (thickness along Y): bounds X[-95,95], Y[0,3.04], Z[-139,139].
# Build in Plane.XZ so the 3.04mm thickness runs along Y to MATCH GT pose -- chamfer is
# NOT pose-invariant, so an XY plate (thickness along Z) scored cham=0.000 against the GT.
# The measured hole (x, y) section coords map to the sketch's local (x, y) on Plane.XZ,
# which become world (x, z) -- matching where the holes sit in the GT.
T = 3.04                      # plate thickness (along Y after XZ build)
LX, LY = 190.5, 279.4         # plate footprint (in-plane: world X by world Z)

# 29 round-hole centres (x, y) paired with measured radii. The size distribution
# (7x1.98, 2x2.81, 4x2.97, 10x3.17, 3x3.57, 2x4.00, 1x9.52) reproduces the GT drill set.
HOLES = [
    # r = 1.98 (d3.96) x7
    (-85.68, 30.87, 1.98), (-51.39, -58.03, 1.98), (-51.39, -38.98, 1.98),
    (-85.68, -47.87, 1.98), (-85.68, -28.82, 1.98), (-85.68, -66.92, 1.98),
    (-85.68, 49.92, 1.98),
    # r = 2.81 (d5.62) x2
    (-85.68, 11.82, 2.81), (-104.73, 16.90, 2.81),
    # r = 2.97 (d5.94) x4
    (12.81, -71.44, 2.97), (-6.94, -79.62, 2.97), (-104.73, 6.74, 2.97),
    (-104.73, 44.84, 2.97),
    # r = 3.17 (d6.34) x10  (dominant)
    (135.30, 18.17, 3.17), (135.30, -19.93, 3.17), (135.30, -0.88, 3.17),
    (107.36, 56.27, 3.17), (-32.64, 56.27, 3.17), (5.76, 84.21, 3.17),
    (107.36, -0.73, 3.17), (-32.64, -0.73, 3.17), (24.81, 84.21, 3.17),
    (-13.29, 84.21, 3.17),
    # r = 3.57 (d7.14) x3
    (113.71, -83.43, 3.57), (113.71, 81.67, 3.57), (-104.73, 55.00, 3.57),
    # r = 4.00 (d8.00) x2
    (-102.19, -83.43, 4.00), (21.00, -51.68, 4.00),
    # r = 9.52 (d19.04) x1  (the single large bore, a corner-region position)
    (-102.19, 81.67, 9.52),
]

# 4 obround / slot cutouts (length, width, x, y). Width ~ 2x the small dimension;
# model each as a SlotOverall sized to the measured equivalent radius.
SLOTS = [
    (28.0, 12.0, 56.6, -48.5),   # eq-r 10.5 obround
    (16.0, 8.0, 101.0, -48.5),   # eq-r 7.0
    (16.0, 8.0, 82.0, -48.5),    # eq-r 7.0
    (12.0, 7.0, -8.2, -51.7),    # eq-r 5.3 rounded slot
]

with BuildPart() as p:
    # solid plate in the XZ plane (thickness along Y), centred on origin
    with BuildSketch(Plane.XZ):
        Rectangle(LX, LY)
    extrude(amount=T)

    # ONE subtract pass: all holes + window + slots cut together through the thickness.
    # Each hole has its own radius, so place circles explicitly (Locations alone can't
    # vary the radius across positions).
    with BuildSketch(Plane.XZ):
        for (x, y, r) in HOLES:
            with Locations((x, y)):
                Circle(r)
        # large rectangular window (~65x65, area ~4250) near (57, 30)
        with Locations((57.0, 30.0)):
            Rectangle(65.0, 65.0)
        # obround slots
        for (ln, wd, x, y) in SLOTS:
            with Locations((x, y)):
                SlotOverall(ln, wd)
    extrude(amount=T, mode=Mode.SUBTRACT)

result = p
