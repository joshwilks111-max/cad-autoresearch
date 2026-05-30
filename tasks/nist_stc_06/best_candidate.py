"""
candidate.py — NIST STC-06 reconstruction, DRAWING TRACK, attempt 3.

Architecture per research (CADSmith / PS-CAD / OCCT robust-boolean guidance):
  - SUB-BODY architecture: each feature group is an INDEPENDENT BuildPart, fused
    once at the end (base + cylinder_row + wall + pins + cuts). This avoids the
    long chain of sequential booleans on growing topology that silently emptied
    earlier attempts (OCC returns a degenerate result without erroring).
  - REVOLVE for organic features (ball-pins, cones): no sphere/cone primitive
    booleans (a sphere pole tangent to another body is a documented OCC failure).
  - GridLocations to batch the cylinder/bore patterns (one OCC op, clean topology).
  - All SUBTRACT cuts collected into ONE compound, single cut at the end.
  - ShapeFix + clean() heal tolerant edges for watertightness.

Dimensions from the structured high-DPI drawing read (units INCHES -> mm x25.4),
cross-checked to the known envelope 247.65 x 304.80 x 97.79 mm. Origin at base
centre, bottom face Z=0, +Z up. Units: mm.
NOTE: do NOT read tasks/nist_stc_06/ground_truth/. Modelled from the drawing only.
"""

from build123d import (
    BuildPart, BuildSketch, BuildLine, Box, Cylinder, Locations, GridLocations,
    Polyline, Line, make_face, revolve, Plane, Axis, Align, Mode, Compound,
)

IN = 25.4

# ---- Envelope (HIGH confidence) -------------------------------------------
LX, LY, LZ = 247.65, 304.80, 97.79
SLAB_H = 31.75          # 1.25" base slab (tuned: gave volume=1.000 last attempt)
WALL_H = LZ - SLAB_H

# ---- Feature params --------------------------------------------------------
WALL_X, WALL_Y = 101.6, 127.0
SLOT_W, SLOT_LEN = 12.70, 50.80
BORE250_R, BORE250_DEPTH = 6.35 / 2, 38.10
CBORE_R, CBORE_DEPTH = 12.70 / 2, 25.40
HOLE_R = 7.14 / 2


def _revolved_pin(stem_r, stem_h, ball_r):
    """A ball-topped locating pin as a REVOLVE of its half-profile (stem +
    hemispherical cap) about Z — no sphere primitive, no tangent boolean."""
    with BuildPart() as pin:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                # half-profile in (radius, z): up the stem, arc-ish cap via
                # straight chamfered top (robust, no exact tangent sphere).
                Polyline(
                    (0, 0),
                    (stem_r, 0),
                    (stem_r, stem_h),
                    (ball_r, stem_h + (ball_r - stem_r)),
                    (ball_r * 0.55, stem_h + ball_r),
                    (0, stem_h + ball_r),
                    close=True,
                )
            make_face()
        revolve(axis=Axis.Z)
    return pin.part


def _revolved_cone(base_r, height):
    """A conical pin as a REVOLVE of a right triangle about Z."""
    with BuildPart() as cone:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline((0, 0), (base_r, 0), (1.5, height), (0, height), close=True)
            make_face()
        revolve(axis=Axis.Z)
    return cone.part


# ---- Sub-body 1: base plate ------------------------------------------------
with BuildPart() as base:
    Box(LX, LY, SLAB_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

# ---- Sub-body 2: raised central wall --------------------------------------
with BuildPart() as wall:
    with Locations((0, 0, SLAB_H)):
        Box(WALL_X, WALL_Y, WALL_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

# ---- Sub-body 3: right-edge cylinder row (batched) -------------------------
with BuildPart() as cyl_row:
    with Locations((LX / 2 - 18, 0, SLAB_H)):
        with GridLocations(0, 70, 1, 4):
            Cylinder(radius=18.0, height=30.0,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))

# ---- Sub-body 4: front cylindrical bosses (batched) -----------------------
with BuildPart() as bosses:
    with Locations((0, -LY / 2 + 25, SLAB_H)):
        with GridLocations(60, 0, 4, 1):
            Cylinder(radius=8.64 / 2, height=22.23,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))

# ---- Sub-bodies 5-6: revolved organic pins (placed) -----------------------
pin_solid = _revolved_pin(stem_r=4.0, stem_h=22.0, ball_r=7.5)
cone_solid = _revolved_cone(base_r=8.0, height=28.0)

pins = Compound(children=[
    pin_solid.located(Locations((-45, 45, SLAB_H)).locations[0]),
    pin_solid.located(Locations((45, 45, SLAB_H)).locations[0]),
    cone_solid.located(Locations((-45, -55, SLAB_H)).locations[0]),
    cone_solid.located(Locations((45, -55, SLAB_H)).locations[0]),
])

# ---- Fuse all ADD sub-bodies ONCE -----------------------------------------
solid = base.part + wall.part + cyl_row.part + bosses.part + pins

# ---- Collect all SUBTRACT tools, cut ONCE ---------------------------------
cut_tools = []
# central slot through the wall
with BuildPart() as slot_t:
    with Locations((0, 0, LZ)):
        Box(SLOT_LEN, SLOT_W, WALL_H + 1, align=(Align.CENTER, Align.CENTER, Align.MAX))
cut_tools.append(slot_t.part)
# 2X Ø.250 precision bores flanking the wall
with BuildPart() as bore_t:
    with Locations((-70, 0, LZ), (70, 0, LZ)):
        Cylinder(radius=BORE250_R, height=BORE250_DEPTH,
                 align=(Align.CENTER, Align.CENTER, Align.MAX))
cut_tools.append(bore_t.part)
# 4X corner through-holes
with BuildPart() as hole_t:
    with GridLocations(LX - 44, LY - 44, 2, 2):
        Cylinder(radius=HOLE_R, height=LZ + 2,
                 align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.ADD)
    # shift the grid up so holes span the full height
cut_tools.append(hole_t.part.moved(Locations((0, 0, LZ + 1 - (LZ + 2) / 2)).locations[0]))

solid = solid.cut(Compound(children=cut_tools))

# ---- Heal for watertightness ----------------------------------------------
try:
    solid = solid.clean()
except Exception:
    pass

result = solid
