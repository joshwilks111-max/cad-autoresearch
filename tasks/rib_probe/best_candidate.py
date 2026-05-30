from build123d import *
with BuildPart() as p:
    Box(80,40,5, align=(Align.CENTER,Align.CENTER,Align.MIN))
    with Locations((0,0,5)):
        with GridLocations(12,20,6,2): Box(2,4,6,align=(Align.CENTER,Align.CENTER,Align.MIN))
result=p