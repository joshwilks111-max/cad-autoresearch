from build123d import BuildPart, Box, Locations, Align
with BuildPart() as p:
    with Locations((-40,0,0),(40,0,0)):
        Box(30, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
result = p
