#!/usr/bin/env python3
"""
make_ground_truth.py — build the motor_mount ground truth.

A synthetic spec-track part, a deliberate step up from sample_bracket: it exercises
multiple feature types (base plate + a revolve-friendly cylindrical hub + an axial
bore + a batched mounting-hole pattern + a chamfer) so the topology layer is a real
test, while staying simple enough to reconstruct to >=0.95. Used to validate the
full loop (scaffold -> ground truth -> spec -> reconstruct -> grade) end to end.

Geometry (mm, centred on origin, base bottom at Z=0):
  - Base plate: 100 (X) x 70 (Y) x 10 (Z).
  - Central cylindrical hub: radius 20, height 25, rising from the plate top (Z=10).
  - Axial bore: radius 8, through the hub AND the plate (full Z), centred.
  - 4 mounting holes: radius 2.5, through the plate, at (+/-40, +/-25).
  - Chamfer: 2 mm on the top circular edge of the hub.

Produces ground_truth/result.step|stl + meta.json + topology.json (with euler).
"""
from pathlib import Path
import json

from build123d import (BuildPart, Box, Cylinder, Hole, Locations, GridLocations,
                       chamfer, Align, Axis, Mode, GeomType, export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)


def build():
    with BuildPart() as p:
        # Base plate (bottom on Z=0).
        Box(100, 70, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Central hub rising from the plate top.
        with Locations((0, 0, 10)):
            Cylinder(radius=20, height=25, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Axial bore through hub + plate (full height), centred.
        with Locations((0, 0, 35)):
            Cylinder(radius=8, height=35, align=(Align.CENTER, Align.CENTER, Align.MAX),
                     mode=Mode.SUBTRACT)
        # 4 mounting holes through the plate (batched pattern).
        with Locations((0, 0, 10)):
            with GridLocations(80, 50, 2, 2):
                Hole(radius=2.5)
        # Chamfer the top circular edge of the hub (highest circular edge).
        top_circle = (p.edges().filter_by(GeomType.CIRCLE)
                      .group_by(Axis.Z)[-1])
        chamfer(top_circle, length=2)
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
    sig = {"faces": _f, "edges": _e,
           "vertices": _v, "shells": c(TopAbs_SHELL),
           "solids": c(TopAbs_SOLID),
           "euler": _v - _e + _f}
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 1) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
