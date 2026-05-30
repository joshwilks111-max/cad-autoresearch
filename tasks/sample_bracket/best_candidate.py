from build123d import *
with BuildPart() as p:
    Box(80, 50, 8)
    with Locations((-30,-18,0),(30,-18,0),(-30,18,0),(30,18,0)): Hole(radius=2.5)
    with BuildSketch(): SlotOverall(30, 8)
    extrude(amount=-8, mode=Mode.SUBTRACT)
result = p
