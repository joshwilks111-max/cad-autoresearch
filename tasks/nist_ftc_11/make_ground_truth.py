#!/usr/bin/env python3
"""
make_ground_truth.py — build the NIST FTC-11 ground truth from the provided STEP.

This task's ground truth IS a real, externally-authored part: NIST PMI test case FTC-11
(Free Toleranced Case 11), AP203 geometry-only edition.  It is the SMALLEST part in the
NIST PMI test suite (~7.6 KB STEP, 6 faces) — a flat square plate.  We ingest the STEP
and emit the artifacts the grader needs:

    ground_truth/result.step      (the canonical B-rep, already placed here)
    ground_truth/result.stl       (mesh the grader samples)
    ground_truth/topology.json    (face/edge/vertex/shell/solid counts + euler)
    ground_truth/meta.json        (volume, bbox)

Source STEP: NIST-PMI-STEP-Files/AP203 geometry only/nist_ftc_11_asme1_rb.stp, from
    https://pages.nist.gov/CAD-PMI-Testing/  (US Government work — unrestricted).

This is a 6-face prismatic plate (bbox ~63 × 63 × 3 mm, volume ~5129 mm³).
Default track: drawing (no hand-authored spec — the agent reads drawing.png).

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
                    help="path to the FTC-11 STEP file (default: ground_truth/result.step "
                         "if already present, else look in ../../_staging/nist/)")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    dst_step = OUT / "result.step"

    # Resolve the source STEP: explicit --src, else an existing result.step, else
    # extract from the staged NIST zip.
    if args.src:
        src = Path(args.src)
        if src.resolve() != dst_step.resolve():
            shutil.copyfile(src, dst_step)
    elif dst_step.exists():
        src = dst_step
    else:
        # Try to extract from the NIST zip if the STEP isn't already here
        staged_zip = HERE.parents[1] / "_staging" / "nist" / "NIST-PMI-STEP-Files.zip"
        if staged_zip.exists():
            import zipfile
            with zipfile.ZipFile(staged_zip) as z:
                data = z.read(
                    "NIST-PMI-STEP-Files/AP203 geometry only/nist_ftc_11_asme1_rb.stp")
            dst_step.write_bytes(data)
            print(f"Extracted {len(data)} bytes from NIST zip -> {dst_step}")
        else:
            raise SystemExit(
                f"FTC-11 STEP not found at {dst_step}. Provide it via --src or place it at "
                f"{dst_step}.")

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
        e = TopExp_Explorer(w, kind)
        s = set()
        while e.More():
            s.add(e.Current().__hash__())
            e.Next()
        return len(s)

    _f = c(TopAbs_FACE)
    _e = c(TopAbs_EDGE)
    _v = c(TopAbs_VERTEX)
    sig = {
        "faces": _f,
        "edges": _e,
        "vertices": _v,
        "shells": c(TopAbs_SHELL),
        "solids": c(TopAbs_SOLID),
        "euler": _v - _e + _f,   # Euler characteristic (matches grader)
    }
    (OUT / "topology.json").write_text(json.dumps(sig, indent=2))

    print("ground truth written to", OUT)
    print("  volume:", round(meta["volume"], 2), "mm^3")
    print("  bbox  :", [round(x, 3) for x in meta["bbox"]], "mm")
    print("  topo  :", sig)


if __name__ == "__main__":
    main()
