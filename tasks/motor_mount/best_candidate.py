from build123d import *

with BuildPart() as p:
    # Base plate 100x70x10, bottom on Z=0
    Box(100, 70, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Hub: r=20, h=25, base at Z=10, top at Z=35
    with Locations((0, 0, 10)):
        Cylinder(radius=20, height=25, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Axial bore through full height Z=0..35: subtract r=8 cylinder h=35
    with Locations((0, 0, 0)):
        Cylinder(radius=8, height=35, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)

    # 4 mounting holes through plate: radius=2.5 at the 4 corners
    with Locations((-40, -25, 10), (40, -25, 10), (-40, 25, 10), (40, 25, 10)):
        Cylinder(radius=2.5, height=10, align=(Align.CENTER, Align.CENTER, Align.MAX),
                 mode=Mode.SUBTRACT)

    # Hub top chamfer: 2mm on the top circular edge of hub (at Z=35)
    hub_top_edges = p.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1]
    chamfer(hub_top_edges, length=2)

result = p
