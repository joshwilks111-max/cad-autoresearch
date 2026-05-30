from build123d import *

with BuildPart() as p:
    # Outer shell 80x60x30, aligned at MIN z
    Box(80, 60, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # Subtract inner box 76x56x30, offset 2mm up (open top tray: no top face)
    with Locations((0, 0, 2)):
        Box(76, 56, 30, align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

result = p
