#!/usr/bin/env python3
"""
make_ground_truth.py — hex_bolt ground truth.

A MIXED prismatic + round spec-track part: a hex-head shoulder bolt. Coaxial about Z:
  - Hex head: a regular hexagon, across-flats 24 mm (circumradius 24/sqrt(3)=13.856 mm),
    extruded 10 mm (Z 0..10). build123d RegularPolygon(radius=circumradius, side_count=6).
  - Shank: cylinder radius 8 mm (Ø16), length 40 mm, on top of the head (Z 10..50), coaxial.
  - 1 mm x 45deg chamfer on the top edge of the shank (the r=8 rim at Z=50).
  - 0.8 mm x 30deg chamfer around the top outer edge of the hex head (Z=10).

The hex head breaks the pure round profile, so this is a useful contrast to the fully
round parts (stepped_hub, pulley_vgroove, ...). Whether the rotational-symmetry gate
fires on a hexagon (6-fold in-plane symmetry gives near-isotropic in-plane covariance)
is reported by the scaffold's symmetry probe, NOT assumed here.
"""
from pathlib import Path
from math import sqrt
import json

from build123d import (BuildPart, BuildSketch, RegularPolygon, Cylinder, Locations,
                       Align, Axis, GeomType, Mode, extrude, chamfer,
                       export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)

ACROSS_FLATS = 24.0
CIRCUMRADIUS = ACROSS_FLATS / sqrt(3)   # 13.8564 mm
HEAD_H = 10.0
SHANK_R = 8.0
SHANK_H = 40.0


def build():
    with BuildPart() as p:
        # --- hex head: regular hexagon extruded Z 0..10 -----------------------
        with BuildSketch() as hs:
            RegularPolygon(radius=CIRCUMRADIUS, side_count=6)
        extrude(hs.sketch, amount=HEAD_H)
        # --- shank: Ø16 cylinder on top of the head, Z 10..50 -----------------
        with Locations((0, 0, HEAD_H)):
            Cylinder(radius=SHANK_R, height=SHANK_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        # --- 1 mm x 45deg chamfer on the top rim of the shank (r=8 @ Z=50) ----
        top_rim = (p.edges().filter_by(GeomType.CIRCLE)
                   .group_by(Axis.Z)[-1]
                   .sort_by(lambda e: e.radius)[-1:])
        chamfer(top_rim, length=1.0)
        # --- 0.8 mm x 30deg chamfer around the hex head top outer edge (Z=10) -
        # the 6 straight edges of the hexagon at the head/shank junction plane.
        head_top = p.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[1]
        head_top_outer = head_top.filter_by(GeomType.LINE)
        chamfer(head_top_outer, length=0.8, angle=30.0)
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
