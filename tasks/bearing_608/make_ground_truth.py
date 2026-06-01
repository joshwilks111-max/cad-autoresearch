#!/usr/bin/env python3
"""
make_ground_truth.py — build the bearing_608 ground truth.

The ground truth is the envelope of a standard **608 bearing** (the classic 608/608ZZ
size): an annular ring with the ISO-standard dimensions OD 22 mm / bore 8 mm / width
7 mm. These are public standard dimensions (not creative IP), so the GT is constructed
here directly from those dimensions rather than redistributing a third-party STEP —
the result is the identical part, with self-contained provenance.

It is a LOW-face real-standard part (4 faces, euler 2), the tractable class of NIST
FTC-11 (the only solvable NIST part; the rest of the NIST PMI suite is 117-270 faces and
topology-capped). Added to give a second SOLVED real part on the cylindrical-IoU path.

Emits the artifacts the grader needs:
    ground_truth/result.step      (canonical B-rep)
    ground_truth/result.stl       (mesh the grader samples)
    ground_truth/topology.json    (face/edge/vertex/shell/solid counts + euler)
    ground_truth/meta.json        (volume, bbox)

Geometry: annular ring, OD 22 (r11) / bore 8 (r4) / thickness 7 mm, vol ~2309 mm^3.
Default track: spec (a simple round part; spec.md gives the three dimensions).
"""
from pathlib import Path
import json

from build123d import (BuildPart, Cylinder, Align, Mode,
                       export_step, export_stl)

HERE = Path(__file__).resolve().parent
OUT = HERE / "ground_truth"

# Standard ISO 608 bearing envelope (mm).
OD_R = 11.0      # outer radius (Ø22)
BORE_R = 4.0     # bore radius (Ø8)
WIDTH = 7.0      # axial width


def build():
    with BuildPart() as p:
        Cylinder(radius=OD_R, height=WIDTH,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))
        Cylinder(radius=BORE_R, height=WIDTH,
                 align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    return p.part


def main():
    OUT.mkdir(exist_ok=True)
    solid = build()
    export_step(solid, str(OUT / "result.step"))
    export_stl(solid, str(OUT / "result.stl"), tolerance=0.02)

    bb = solid.bounding_box()
    meta = {"volume": float(abs(solid.volume)),
            "bbox": [float(bb.size.X), float(bb.size.Y), float(bb.size.Z)]}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2))

    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX,
                            TopAbs_SHELL, TopAbs_SOLID)
    w = solid.wrapped

    def c(kind):
        e = TopExp_Explorer(w, kind)
        s = set()
        while e.More():
            s.add(e.Current().__hash__())
            e.Next()
        return len(s)

    _f, _e, _v = c(TopAbs_FACE), c(TopAbs_EDGE), c(TopAbs_VERTEX)
    sig = {"faces": _f, "edges": _e, "vertices": _v,
           "shells": c(TopAbs_SHELL), "solids": c(TopAbs_SOLID),
           "euler": _v - _e + _f}
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 3) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
