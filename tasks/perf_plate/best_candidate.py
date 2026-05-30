from build123d import *
with BuildPart() as p:
    Box(60,40,4, align=(Align.CENTER,Align.CENTER,Align.MIN))
    with Locations((0,0,4)):
        with GridLocations(11,11,5,3): Hole(radius=2.5)
result=p