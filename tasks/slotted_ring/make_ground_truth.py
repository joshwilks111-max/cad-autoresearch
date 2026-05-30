#!/usr/bin/env python3
"""
make_ground_truth.py — slotted_ring ground truth.

A castle-nut-style SLOTTED RING (collar) — a near-round part whose 6 axial slots
deliberately PROBE the rotational-symmetry gate (harness.geometry._is_rotationally_
symmetric / iou). The collar is rotationally symmetric, but the 6 slots cut into the
top face break perfect symmetry; the question this task answers is whether the slots
perturb the covariance eigenvalues enough to flip the part off the cylindrical IoU
path onto the prismatic voxel path. The slots are a small fraction of the volume, so
the gate is expected to STILL read symmetric (two near-equal eigenvalues) — reported
honestly by the symmetry-check scratch alongside the GT.

Coaxial about Z, base bottom on Z=0:
  - Collar: annular ring, outer radius 25 mm, inner bore radius 14 mm, height 18 mm
    (Z 0..18). Wall thickness 11 mm.
  - Slots: 6 rectangular slots cut radially into the TOP face, evenly spaced at 60deg
    (PolarLocations), each 5 mm wide x 8 mm deep (Z 10..18), spanning the full wall
    thickness radially (the box cutter is long enough in radius to clear both walls).
  - Chamfer: 1 mm x 45deg on the top outer edge (the Ø50 rim at Z=18).

Single watertight solid. Mirrors the OCP topology-count idiom + meta.json/topology.json
layout of tasks/stepped_hub/make_ground_truth.py.
"""
from pathlib import Path
import json

from build123d import (BuildPart, Cylinder, Box, Locations, PolarLocations,
                       Align, Axis, GeomType, Mode, chamfer,
                       export_step, export_stl)

OUT = Path(__file__).resolve().parent / "ground_truth"
OUT.mkdir(exist_ok=True)

R_OUT = 25.0      # collar outer radius (Ø50)
R_BORE = 14.0     # inner bore radius (Ø28)
H = 18.0          # collar height
SLOT_W = 5.0      # slot width (tangential)
SLOT_DEPTH = 8.0  # slot depth (axial): cut Z 10..18
N_SLOTS = 6
SLOT_Z0 = H - SLOT_DEPTH   # 10.0


def build():
    with BuildPart() as p:
        # Annular collar: outer cylinder minus the central bore.
        Cylinder(radius=R_OUT, height=H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Cylinder(radius=R_BORE, height=H, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)

        # 6 radial slots cut into the TOP face, polar-patterned at 60deg.
        # Each slot cutter is a box centred on the wall mid-radius, spanning the
        # full wall thickness in the radial (local-X) direction with margin, SLOT_W
        # wide tangentially (local-Y), SLOT_DEPTH tall, top-aligned at Z=H.
        slot_len = (R_OUT - R_BORE) + 6.0     # radial extent, +margin to clear walls
        wall_mid = (R_OUT + R_BORE) / 2.0     # 19.5
        with Locations((0, 0, H)):
            with PolarLocations(radius=wall_mid, count=N_SLOTS):
                Box(slot_len, SLOT_W, SLOT_DEPTH,
                    align=(Align.CENTER, Align.CENTER, Align.MAX),
                    mode=Mode.SUBTRACT)

        # 1 mm x 45deg chamfer on the top outer edge (the Ø50 rim at Z=H). After the
        # slots, the rim is broken into 6 arcs; chamfer every top circular edge at the
        # outer radius. Select circular edges in the top Z-group at the largest radius.
        top_outer = (p.edges().filter_by(GeomType.CIRCLE)
                     .group_by(Axis.Z)[-1]
                     .filter_by(lambda e: abs(e.radius - R_OUT) < 1e-3))
        chamfer(top_outer, length=1)
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
