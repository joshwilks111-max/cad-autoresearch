#!/usr/bin/env python3
"""
make_ground_truth.py — pulley_vgroove ground truth.

A clean, fully ROUND (rotationally-symmetric) spec-track part — a V-belt pulley.
A NEW grooved profile distinct from stepped_hub, used to validate the cylindrical
round-part IoU on a vee-notch cross-section end to end to >=0.95.

Coaxial about Z, mid-plane at Z=0 (so faces are symmetric about Z=0):
  - Pulley disc: outer radius 40 (Ø80), total width 20 (Z -10..+10).
  - V-groove around the OD: 40deg included angle vee, ~12 mm deep, centered on the
    mid-plane -> groove ROOT radius 28 (Ø56). The vee mouth at the OD spans
    z = +/- 12*tan(20deg) = +/- 4.368 mm, comfortably inside the disc half-width.
  - Hub: raised boss radius 20 (Ø40) extending 6 mm beyond EACH face -> hub width 32
    (Z -16..+16), concentric.
  - Central bore radius 10 (Ø20) through the full hub width.
  - 1 mm chamfer on BOTH bore mouths.

The whole solid is built by revolving the (r, z) half-cross-section 360deg about Z,
so it is rotationally symmetric -> iou() takes the cylindrical path. Reachable to
>=0.95 (caps near the chamfer/sampling floor).
"""
from pathlib import Path
import json
import math

from build123d import (BuildPart, BuildSketch, BuildLine, Plane, Polyline,
                        make_face, revolve, Cylinder, Locations, Align, Axis,
                        GeomType, Mode, chamfer, export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)

# --- design parameters (mm) -------------------------------------------------
R_OD = 40.0          # disc outer radius
W_DISC = 20.0        # disc total width  -> half = 10
R_HUB = 20.0         # hub boss radius
W_HUB = 32.0         # hub total width   -> half = 16
R_BORE = 10.0        # central bore radius
GROOVE_DEPTH = 12.0  # radial depth of the vee from OD -> root radius 28
GROOVE_HALF_ANGLE = math.radians(20.0)   # 40deg included
CHAMFER = 1.0        # bore-mouth chamfer

_disc_h = W_DISC / 2.0                                   # 10
_hub_h = W_HUB / 2.0                                     # 16
_root_r = R_OD - GROOVE_DEPTH                            # 28
_groove_half_w = GROOVE_DEPTH * math.tan(GROOVE_HALF_ANGLE)  # ~4.368


def build():
    # Half cross-section in the X(r)-Z plane, r >= 0, walked CCW. Revolving this
    # 360deg about the Z axis sweeps the full solid (bore handled separately so the
    # axis stays inside material and the profile is a clean closed loop on r in
    # [0, R_OD]).
    pts = [
        (0.0,      _hub_h),            # top, on axis (hub top face)
        (R_HUB,    _hub_h),            # hub top face out to boss radius
        (R_HUB,    _disc_h),           # step down: hub face -> disc face (+z)
        (R_OD,     _disc_h),           # disc top face out to OD
        (R_OD,     _groove_half_w),    # OD wall down to vee mouth (+z)
        (_root_r,  0.0),               # vee in to root (mid-plane)
        (R_OD,    -_groove_half_w),    # vee back out to OD (-z)
        (R_OD,    -_disc_h),           # OD wall down to disc bottom face
        (R_HUB,   -_disc_h),           # disc bottom face in to boss radius
        (R_HUB,   -_hub_h),            # step up: disc face -> hub face (-z)
        (0.0,     -_hub_h),            # hub bottom face to axis
        (0.0,      _hub_h),            # close up the axis edge
    ]

    with BuildPart() as p:
        with BuildSketch(Plane.XZ) as sk:
            with BuildLine():
                Polyline(*pts)
            make_face()
        revolve(sk.sketch, axis=Axis.Z)

        # Central axial bore through the full hub width.
        Cylinder(radius=R_BORE, height=W_HUB + 2,
                 align=(Align.CENTER, Align.CENTER, Align.CENTER),
                 mode=Mode.SUBTRACT)

        # 1 mm chamfer on both bore mouths (the two Ø20 circles on the hub faces).
        bore_edges = (p.edges().filter_by(GeomType.CIRCLE)
                      .filter_by(lambda e: abs(e.radius - R_BORE) < 1e-6))
        chamfer(bore_edges, length=CHAMFER)
    return p.part


def main():
    solid = build()
    export_step(solid, str(OUT / "result.step"))
    export_stl(solid, str(OUT / "result.stl"), tolerance=0.05)

    bb = solid.bounding_box()
    meta = {"volume": float(abs(solid.volume)),
            "bbox": [float(bb.size.X), float(bb.size.Y), float(bb.size.Z)]}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2))

    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX,
                            TopAbs_SHELL, TopAbs_SOLID)
    w = solid.wrapped

    def c(kind):
        e = TopExp_Explorer(w, kind); s = set()
        while e.More():
            s.add(e.Current().__hash__()); e.Next()
        return len(s)

    _f = c(TopAbs_FACE); _e = c(TopAbs_EDGE); _v = c(TopAbs_VERTEX)
    sig = {"faces": _f, "edges": _e, "vertices": _v,
           "shells": c(TopAbs_SHELL), "solids": c(TopAbs_SOLID),
           "euler": _v - _e + _f}
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 1) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
