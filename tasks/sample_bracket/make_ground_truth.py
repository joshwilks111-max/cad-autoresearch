#!/usr/bin/env python3
"""
make_ground_truth.py — build the sample-bracket ground truth.

Produces the reference artifacts the harness grades against:
    ground_truth/result.step      (B-rep, the canonical artifact)
    ground_truth/result.stl       (mesh, used by the grader)
    ground_truth/topology.json    (face/edge/vertex/shell/solid counts)
    ground_truth/meta.json        (volume, bbox)

Geometry: an 80 x 50 x 8 mm plate, four M5 clearance holes (r=2.5) at
(+/-30, +/-18), and a central 30 x 8 slot cut clean through. Deliberately simple
so the offline mock loop can reach composite ~1.0 and prove the pipeline end to
end. Replace with real parts (NIST PMI / Model Mania) for actual research.
"""
from pathlib import Path
import json

from build123d import (BuildPart, BuildSketch, Box, Hole, Locations,
                        SlotOverall, extrude, Mode, export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)


def build():
    with BuildPart() as p:
        Box(80, 50, 8)
        with Locations((-30, -18, 0), (30, -18, 0), (-30, 18, 0), (30, 18, 0)):
            Hole(radius=2.5)
        with BuildSketch():
            SlotOverall(30, 8)
        extrude(amount=-8, mode=Mode.SUBTRACT)
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
           "euler": _v - _e + _f}   # Euler characteristic (matches grader)
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 1) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
