# trial_lbracket

A gusseted **L-bracket** — bread-and-butter mechanical CAD. This spec is the design
intent (the input both the human and the AI competitor receive in the time trial; see
`timetrial/PROTOCOL.md`). All dimensions in mm. Origin at the centre of the base plate's
bottom face; Z up.

## Features
1. **Base plate** — 120 (X) × 60 (Y) × 8 (Z). Bottom face on Z=0, centred on the origin
   in X and Y.
2. **Upright wall** — 120 (X) × 8 (Y, thickness) × 36 (Z, height), standing on the plate
   top (rises from Z=8 to Z=44). Flush with the plate's back edge: the wall's outer face
   is at Y=+30, its front face at Y=+22 (wall centred on Y=+26).
3. **Gusset rib** — a right-triangular rib in the Y–Z plane bridging the plate top and
   the wall front, 8 mm thick (centred on X=0). Right-angle corner at the wall front
   face (Y=+22) on the plate top (Z=8); legs 24 mm — one running forward along the plate
   (to Y=−2), one up the wall front (to Z=32); hypotenuse closes them.
4. **Base bolt holes** — 4 × Ø8 (radius 4) through holes in the base plate, at
   (X=±45, Y=±18).
5. **Wall bolt holes** — 2 × Ø8 (radius 4) through holes in the upright wall (bored along
   Y, through the 8 mm thickness), at X=±45, Z=26 (i.e. 18 mm above the plate top).
6. **Chamfer** — 3 mm on the two outer **vertical** front edges of the upright wall.

## Target
Single prismatic solid, ~17 B-rep faces, watertight. Reachable to the "solved" bar
(composite ≥ ~0.95) — it is a clean prismatic part with distinct X/Y/Z extents (so the
referee's volumetric IoU uses the voxel path).
