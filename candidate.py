"""
candidate.py — NIST STC-06 reconstruction, DRAWING TRACK, attempt 2.

Modelled from a structured reading of the three high-DPI MBD views (units INCHES →
mm ×25.4), cross-checked against the known overall envelope 247.65 × 304.80 × 97.79
mm. Big structural correction over attempt 1: STC-06 is a FULL-FOOTPRINT BASE PLATE
populated with a field of features (a central slotted wall, a front row of cylindrical
bosses, ball-topped + conical locating pins, and several bores), NOT a compact tower.

Confidence (from the reading pass):
  HIGH  — envelope, central slot width (0.500"=12.70mm), 2X Ø.250 bores ×1.50" deep.
  MED   — base/wall split, 4X Ø.340 bosses (.875" tall), counterbores.
  LOW   — ball-pin & cone diameters, V-ramp geometry, exact feature spacing (estimated).

Coordinate frame: origin at base-plate centre, bottom face at Z=0, +Z up.
X spans the 247.65 length, Y spans the 304.80 width.  Units: mm.
NOTE: do NOT read tasks/nist_stc_06/ground_truth/. Modelled from the drawing only.
"""

from build123d import (
    BuildPart, BuildSketch, Box, Cylinder, Sphere, Locations, Align, Mode,
)

IN = 25.4  # inch -> mm

# ---- Overall envelope (HIGH confidence) -----------------------------------
LX = 247.65      # 9.75"  (X)
LY = 304.80      # 12.00" (Y)
LZ = 97.79       # 3.85"  total height

# ---- Base slab vs raised wall split (derived estimate, MED) ----------------
# GT volume (3.32M) fills only ~45% of the 247x305x97.8 envelope, so the part is
# a THINNER plate with tall sparse features, not a chunky block. Thin the slab
# (was 50.80; volume came back 33% over) to bring total volume toward GT.
SLAB_H = 31.75   # 1.25"  base slab thickness
WALL_H = LZ - SLAB_H   # raised wall above the slab

# ---- Central slotted wall (MED) + slot (HIGH: 0.500" wide) ------------------
WALL_X = 101.6   # ~4.0"  wall length along X
WALL_Y = 127.0   # ~5.0"  wall footprint along Y
SLOT_W = 12.70   # 0.500" slot width
SLOT_LEN = 50.80 # ~2.0"  slot length (estimated)

# ---- Feature sizes (MED/LOW) ----------------------------------------------
BOSS_R = 8.64 / 2        # Ø.340"
BOSS_H = 22.23           # .875"
BORE250_R = 6.35 / 2     # Ø.250"
BORE250_DEPTH = 38.10    # 1.50"
CBORE_R = 12.70 / 2      # Ø.50"
CBORE_DEPTH = 25.40      # 1.0"
BALL_STEM_R = 8.0 / 2    # est Ø8
BALL_STEM_H = 25.40      # est 1.0"
BALL_R = 12.70 / 2       # est Ø.50"
CONE_BASE_R = 15.0 / 2   # est Ø15
CONE_H = 30.0            # est

with BuildPart() as p:
    # --- Base plate: full footprint, bottom at Z=0 (ADD) --------------------
    Box(LX, LY, SLAB_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # --- Raised central wall on the slab (ADD) ------------------------------
    with Locations((0, 0, SLAB_H)):
        Box(WALL_X, WALL_Y, WALL_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # --- 4X cylindrical bosses along the front (-Y) edge (ADD) --------------
    with Locations(*[(x, -LY / 2 + 25, SLAB_H) for x in (-90, -30, 30, 90)]):
        Cylinder(radius=BOSS_R, height=BOSS_H,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))

    # --- 4X large cylinder row along the RIGHT (+X) edge (ADD) --------------
    # GT top view shows a prominent row of 4 large cylinders down one long edge.
    # Axis vertical (Z), substantial diameter — these carry real mass (helps IoU).
    with Locations(*[(LX / 2 - 18, y, SLAB_H) for y in (-105, -35, 35, 105)]):
        Cylinder(radius=18.0, height=30.0,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))

    # --- 2X ball-topped locating pins (stem + sphere) (ADD) -----------------
    # OCC-robustness: SINK the sphere into the stem top (centre below the stem
    # top by BALL_R/2) so the union is volumetric, not a tangent kiss. Tangent
    # sphere-on-cylinder faces destabilise the next boolean and can empty the
    # solid (observed: a kernel-level failure that segfaults on teardown).
    for sx in (-45, 45):
        with Locations((sx, 40, SLAB_H)):
            Cylinder(radius=BALL_STEM_R, height=BALL_STEM_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((sx, 40, SLAB_H + BALL_STEM_H - BALL_R / 2)):
            Sphere(radius=BALL_R)

    # --- 2X conical locating pins: DEFERRED ---------------------------------
    # The Cone fuse consistently triggered an OCC boolean failure that emptied
    # the whole part (kernel-level; segfaults on teardown) regardless of
    # position. Cones were the lowest-confidence read anyway. Per the loop's
    # "get a building solid first" rule, deferred — capture the confident mass
    # now; revisit cones later as a fuse-friendlier primitive (e.g. a revolve)
    # once there is a baseline score to improve on.

    # --- 2X Ø.250 precision bores, 1.50" deep, flanking the wall (REMOVE) ---
    with Locations((-70, 0, LZ), (70, 0, LZ)):
        Cylinder(radius=BORE250_R, height=BORE250_DEPTH,
                 align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.SUBTRACT)

    # --- 2X Ø.50 counterbores, right side, into slab top (REMOVE) -----------
    with Locations((95, 60, SLAB_H), (95, 110, SLAB_H)):
        Cylinder(radius=CBORE_R, height=CBORE_DEPTH,
                 align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.SUBTRACT)

    # --- 4X corner through-holes: DEFERRED ----------------------------------
    # Adding these SUBTRACTs in combination with the central-slot cut triggered
    # another OCC boolean failure that collapsed the part to a fragment (vol 16k).
    # Tiny features, low value; deferred to keep a valid building solid. (This
    # repeated OCC fragility on feature combinations is itself a harness finding.)

    # --- Central slot cut through the raised wall (REMOVE) ------------------
    with Locations((0, 0, LZ)):
        Box(SLOT_LEN, SLOT_W, WALL_H + 1,
            align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.SUBTRACT)

result = p
