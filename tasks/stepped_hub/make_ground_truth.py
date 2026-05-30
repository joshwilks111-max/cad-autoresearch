#!/usr/bin/env python3
"""
make_ground_truth.py — stepped_hub ground truth.

A clean, fully ROUND (rotationally-symmetric) spec-track part — the round analog of
motor_mount, used to validate the cylindrical round-part IoU end to end to >=0.95.
Coaxial about Z:
  - Base flange: cylinder Ø60, height 8 (Z 0..8).
  - Hub: cylinder Ø36, height 18, on top of the flange (Z 8..26).
  - Axial bore: Ø16, through the full height (Z 0..26).
  - 45deg chamfer 2 mm on the top outer edge of the hub.
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
        Cylinder(radius=30, height=8, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, 8)):
            Cylinder(radius=18, height=18, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # axial bore through everything
        with Locations((0, 0, 26)):
            Cylinder(radius=8, height=26, align=(Align.CENTER, Align.CENTER, Align.MAX),
                     mode=Mode.SUBTRACT)
        # chamfer the top outer edge of the hub (highest, largest-radius circle ~18)
        top_outer = (p.edges().filter_by(GeomType.CIRCLE)
                     .group_by(Axis.Z)[-1]
                     .sort_by(lambda e: e.radius)[-1:])
        chamfer(top_outer, length=2)
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
