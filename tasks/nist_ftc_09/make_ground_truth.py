#!/usr/bin/env python3
"""
make_ground_truth.py — build the NIST FTC-09 ground truth from the provided STEP.

NIST PMI FTC-09 (Functional Test Case 9) — AP242-e1 annotated part.
From: https://pages.nist.gov/CAD-PMI-Testing/  (US Government work — unrestricted).

Source STEP: nist_ftc_09_asme1_ap242-e1.stp  (~5.9 MB — the largest FTC part; likely
complex with many curved faces, threads, or rich PMI annotation geometry.)

Emits:
    ground_truth/result.step      (canonical B-rep)
    ground_truth/result.stl       (mesh for volumetric grading)
    ground_truth/topology.json    (faces/edges/vertices/shells/solids + euler)
    ground_truth/meta.json        (volume_mm3, bbox_mm)
"""
from pathlib import Path
import argparse
import json
import shutil

from build123d import import_step, export_stl

HERE = Path(__file__).resolve().parent
OUT = HERE / "ground_truth"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None,
                    help="path to the FTC-09 STEP file (default: ground_truth/result.step)")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    dst_step = OUT / "result.step"

    if args.src:
        src = Path(args.src)
    elif dst_step.exists():
        src = dst_step
    else:
        staged = HERE.parents[1] / "_staging" / "nist" / "nist_ftc_09_asme1_ap242-e1.stp"
        src = staged
    if not src.exists():
        raise SystemExit(
            f"FTC-09 STEP not found at {src}. Provide it via --src or place it at "
            f"{dst_step}.")
    if src.resolve() != dst_step.resolve():
        shutil.copyfile(src, dst_step)

    solid = import_step(str(dst_step))
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
