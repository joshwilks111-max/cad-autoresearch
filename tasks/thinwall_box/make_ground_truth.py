#!/usr/bin/env python3
"""
make_ground_truth.py — thin-wall shelled box (ELEMENT PROBE).

Failure hypothesis: the harness IoU layer voxelises interior occupancy at a pitch
of roughly max_extent / 48. For an 80 mm part that is ~3.3 mm per voxel, so a
**2 mm wall is thinner than a single voxel** and may be missed or aliased — making
the volumetric IoU unreliable for thin-walled parts even when the reconstruction is
geometrically perfect. This part exists to test that.

Geometry (mm, centred, bottom on Z=0): an 80 x 60 x 30 outer box, hollowed to a
2 mm wall thickness with an OPEN TOP (a tray/shell). Outer minus an inner pocket of
(80-4) x (60-4) x (30-2), open at the top.
"""
from pathlib import Path
import json

from build123d import (BuildPart, Box, Locations, Align, Mode,
                       export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)

WALL = 2.0
OX, OY, OZ = 80.0, 60.0, 30.0


def build():
    with BuildPart() as p:
        Box(OX, OY, OZ, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Hollow it out from the top, leaving WALL on the 4 sides + bottom, open top.
        with Locations((0, 0, WALL)):
            Box(OX - 2 * WALL, OY - 2 * WALL, OZ,  # tall enough to break the top open
                align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
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
