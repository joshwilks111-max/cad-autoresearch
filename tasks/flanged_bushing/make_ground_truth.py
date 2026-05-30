#!/usr/bin/env python3
"""
make_ground_truth.py — flanged_bushing ground truth.

A clean, fully ROUND (rotationally-symmetric) spec-track part — a flanged sleeve
bushing with a stepped inner diameter. Distinct round profile from stepped_hub /
pulley_vgroove: it stress-tests the cylindrical IoU on a COUNTERBORE (stepped inner
diameter) rather than an outer step or a vee groove.
Coaxial about Z:
  - Sleeve: cylinder Ø30 (r=15), total height 40 (Z 0..40).
  - Base flange: cylinder Ø56 (r=28), height 6 (Z 0..6), concentric.
  - Through bore: Ø18 (r=9), through the full height (Z 0..40).
  - Top counterbore: Ø24 (r=12), depth 8 (Z 32..40) — a stepped inner diameter.
  - 1mm x 45deg chamfer on the top outer rim of the sleeve (r=15 circle at Z=40)
    and on the bore mouth at the bottom (r=9 circle at Z=0).
All features share the Z axis -> the part is rotationally symmetric, so iou() takes
the cylindrical path. Reachable to >=0.95 (caps near the chamfer/sampling floor).
"""
from pathlib import Path
import json

from build123d import (BuildPart, Cylinder, Locations, Align, Axis, GeomType,
                       Mode, chamfer, export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)


def build():
    with BuildPart() as p:
        # Sleeve: outer body, Ø30, full height 40.
        Cylinder(radius=15, height=40, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Base flange: Ø56, height 6, concentric, sitting at the base.
        Cylinder(radius=28, height=6, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Through bore Ø18, through the full height.
        with Locations((0, 0, 40)):
            Cylinder(radius=9, height=40, align=(Align.CENTER, Align.CENTER, Align.MAX),
                     mode=Mode.SUBTRACT)
        # Top counterbore Ø24, depth 8 (Z 32..40) — stepped inner diameter.
        with Locations((0, 0, 40)):
            Cylinder(radius=12, height=8, align=(Align.CENTER, Align.CENTER, Align.MAX),
                     mode=Mode.SUBTRACT)
        # Chamfer the top outer rim of the sleeve: the r=15 circle at the highest Z.
        sleeve_top = (p.edges().filter_by(GeomType.CIRCLE)
                      .group_by(Axis.Z)[-1]
                      .filter_by(lambda e: abs(e.radius - 15) < 1e-6))
        chamfer(sleeve_top, length=1)
        # Chamfer the bore mouth at the bottom: the r=9 circle at the lowest Z.
        bore_bottom = (p.edges().filter_by(GeomType.CIRCLE)
                       .group_by(Axis.Z)[0]
                       .filter_by(lambda e: abs(e.radius - 9) < 1e-6))
        chamfer(bore_bottom, length=1)
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
