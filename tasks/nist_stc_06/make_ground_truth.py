#!/usr/bin/env python3
"""
make_ground_truth.py — build the NIST STC-06 ground truth from the provided STEP.

Unlike the sample_bracket (which constructs geometry from scratch), this task's
ground truth IS a real, externally-authored part: NIST PMI test case STC-06
(Simplified Toleranced Case 6), AP242. We don't model it — we ingest the STEP and
emit the artifacts the grader needs:
    ground_truth/result.step      (the canonical B-rep, copied in)
    ground_truth/result.stl       (mesh the grader samples)
    ground_truth/topology.json    (face/edge/vertex/shell/solid counts + euler)
    ground_truth/meta.json        (volume, bbox)

Source STEP (place it at ground_truth/result.step before running, or pass --src):
    NIST STC-06, file `nist_stc_06_asme1_ap242-e3.stp`, from
    https://pages.nist.gov/CAD-PMI-Testing/  (US Government work — unrestricted).
This is a ~144-face toleranced prismatic part (bbox ~247.65 x 304.80 x 127.89 mm),
a hard drawing-track benchmark: the agent gets STC_06.pdf (drawing.png) and must
read all dimensions/GD&T itself.

The topology signature includes the Euler characteristic (V - E + F), matching the
grader's signature format (harness/geometry.py, harness/runner.py) so candidate and
ground-truth signatures compare key-for-key.
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
                    help="path to the STC-06 STEP file (default: ground_truth/result.step "
                         "if already present, else look in ../../_staging/nist/)")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    dst_step = OUT / "result.step"

    # Resolve the source STEP: explicit --src, else an existing result.step, else
    # the staged NIST download.
    if args.src:
        src = Path(args.src)
    elif dst_step.exists():
        src = dst_step
    else:
        staged = HERE.parents[1] / "_staging" / "nist" / "nist_stc_06_asme1_ap242-e3.stp"
        src = staged
    if not src.exists():
        raise SystemExit(
            f"STC-06 STEP not found at {src}. Provide it via --src or place it at "
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
           "euler": _v - _e + _f}   # Euler characteristic (matches grader)
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 1) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
