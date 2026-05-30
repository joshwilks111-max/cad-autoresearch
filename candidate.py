"""
candidate.py — NIST FTC-11 reconstruction (SPEC track). A round WASHER, modelled by
revolving its exact axial cross-section with TRUE R1.5 fillet ARCS (not a faceted
polyline) so the rims become smooth torus faces matching the GT B-rep.

Cross-section (radius, z), from the GT mesh (WF-H extraction):
  - outer R31.5, bore R16, thickness 3 (z in [-1.5, 1.5]); sharp BOTTOM.
  - TOP-side R1.5 fillets on inner & outer rims: arc centres at r=17.5 and r=30.0
    (z=0), peaking at z=1.5; flat top annular face at z=0.425 (r 18.93..28.55).
Revolving with real arcs reproduces GT volume (~5126) and topology (smooth fillets).
Units: mm.
"""

from build123d import (BuildPart, BuildSketch, BuildLine, Line, ThreePointArc,
                       make_face, revolve, Plane, Axis)

R_IN, R_OUT, T = 16.0, 31.5, 1.5   # bore r, outer r, half-thickness
# Exact profile points (radius, z) from WF-H. The TOP rim fillets are R1.5 arcs that
# bulge UP to a z=1.5 peak — defined via a ThreePointArc through that peak so the
# convex (major) arc is taken, not the minor one.
P_bore_bot = (R_IN, -T)
P_bore_top = (R_IN, 0.0)            # bore wall -> inner fillet (tangent, z=0)
P_in_peak = (17.5, 1.5)            # inner fillet peak (centre r, z=1.5)
P_in_flat = (18.93, 0.425)         # inner fillet -> flat top
P_out_flat = (28.55, 0.425)        # flat top -> outer fillet
P_out_peak = (30.0, 1.5)          # outer fillet peak
P_out_top = (R_OUT, 0.0)           # outer fillet -> outer wall (tangent, z=0)
P_out_bot = (R_OUT, -T)

with BuildPart() as p:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Line(P_bore_bot, P_bore_top)                       # up the bore wall
            ThreePointArc(P_bore_top, P_in_peak, P_in_flat)    # inner top R1.5 fillet
            Line(P_in_flat, P_out_flat)                        # flat top annular face
            ThreePointArc(P_out_flat, P_out_peak, P_out_top)   # outer top R1.5 fillet
            Line(P_out_top, P_out_bot)                         # down the outer wall
            Line(P_out_bot, P_bore_bot)                        # flat bottom
        make_face()
    revolve(axis=Axis.Z)

result = p
