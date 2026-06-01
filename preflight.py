"""
preflight.py — sub-1s build check without full scoring.

Builds a candidate .py, checks watertight/volume/bbox/topology, NO IoU/reward.
Reuses harness.run_candidate verbatim; never imports harness.reward or score().

CLI:  python preflight.py <candidate.py> [--timeout 60] [--json] [--ws <dir>]
API:  preflight(code_or_path, *, timeout=60, workspace=None) -> dict
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def preflight(code_or_path: str, *, timeout: int = 60, workspace: str | None = None) -> dict:
    """
    Build and inspect a candidate without scoring.

    Parameters
    ----------
    code_or_path : str
        Either the Python source code of the candidate, or a path to a .py file.
    timeout : int
        Subprocess wall-clock timeout in seconds.
    workspace : str | None
        Directory to use as workspace. If None, a unique temp dir is created and
        cleaned up automatically. Pass a path to preserve artifacts.

    Returns
    -------
    dict with keys:
        ok, watertight, volume, bbox, faces, edges, vertices, euler,
        solids, shells, seconds, error (on failure also stderr_tail)
    """
    from harness.runner import run_candidate

    # Resolve code: path → read; otherwise treat as raw source
    path = Path(code_or_path)
    if path.suffix.lower() in (".py",) and path.exists():
        code = path.read_text(encoding="utf-8")  # explicit UTF-8: Windows cp1252 trap
        label = str(path)
    else:
        # Treat as raw source (or a non-.py path error is surfaced below)
        code = code_or_path
        label = "<inline>"

    # Unique workspace: never uses runs/manual (shared-workspace race)
    _cleanup = False
    if workspace is None:
        ws = tempfile.mkdtemp(prefix="preflight_")
        _cleanup = True
    else:
        ws = workspace

    try:
        run = run_candidate(code, ws, timeout=timeout)
    finally:
        if _cleanup:
            import shutil
            try:
                shutil.rmtree(ws, ignore_errors=True)
            except Exception:
                pass

    if not run.ok:
        stderr_lines = (run.stderr or "").splitlines()
        return {
            "ok": False,
            "error": run.error,
            "stderr_tail": "\n".join(stderr_lines[-12:]),
        }

    # Pull topology from B-rep dict
    topo = run.topology or {}
    faces = topo.get("faces")
    edges = topo.get("edges")
    vertices = topo.get("vertices")
    euler = topo.get("euler")
    solids = topo.get("solids")
    shells = topo.get("shells")

    # Volume/bbox: prefer run.meta (computed inside sandbox, no recompute)
    meta = run.meta or {}
    volume = meta.get("volume")
    bbox_raw = meta.get("bbox")
    if bbox_raw is not None:
        bbox = sorted(bbox_raw)  # sort ascending for canonical display
    else:
        bbox = None

    # Watertight from loaded trimesh
    watertight = None
    if run.mesh is not None:
        try:
            watertight = bool(run.mesh.is_watertight)
        except Exception:
            pass

    return {
        "ok": True,
        "watertight": watertight,
        "volume": volume,
        "bbox": bbox,
        "faces": faces,
        "edges": edges,
        "vertices": vertices,
        "euler": euler,
        "solids": solids,
        "shells": shells,
        "seconds": run.seconds,
        "error": None,
    }


def _fmt_result(result: dict, label: str) -> str:
    """Format the preflight result as human-readable text."""
    lines = [f"PREFLIGHT  {label}"]
    if not result["ok"]:
        lines.append(f"  ok          : False")
        lines.append(f"  error       : {result.get('error', 'unknown')}")
        tail = result.get("stderr_tail", "")
        if tail:
            lines.append("  stderr tail :")
            for line in tail.splitlines():
                lines.append(f"    {line}")
        return "\n".join(lines)

    vol = result.get("volume")
    vol_str = f"{vol:,.0f} mm³" if vol is not None else "?"

    bbox = result.get("bbox")
    if bbox is not None:
        bbox_str = "[" + ", ".join(f"{v:.1f}" for v in bbox) + "] mm"
    else:
        bbox_str = "?"

    faces = result.get("faces", "?")
    edges = result.get("edges", "?")
    verts = result.get("vertices", "?")
    euler = result.get("euler", "?")
    solids = result.get("solids", "?")
    shells = result.get("shells", "?")
    secs = result.get("seconds", 0.0)

    lines.append(f"  ok          : True")
    lines.append(f"  watertight  : {result.get('watertight')}")
    lines.append(f"  volume      : {vol_str}")
    lines.append(f"  bbox (sorted): {bbox_str}")
    lines.append(f"  faces/edges/verts : {faces} / {edges} / {verts}   (euler {euler})")
    lines.append(f"  solids/shells     : {solids} / {shells}")
    lines.append(f"  build       : {secs:.1f} s")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fast build check for a CAD candidate (no scoring)."
    )
    parser.add_argument("candidate", help="Path to candidate .py (or .step) file")
    parser.add_argument("--timeout", type=int, default=60, help="Build timeout in seconds")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Print result as a single JSON line")
    parser.add_argument("--ws", default=None, metavar="DIR",
                        help="Workspace directory (default: unique temp dir)")
    args = parser.parse_args(argv)

    candidate_path = args.candidate
    result = preflight(candidate_path, timeout=args.timeout, workspace=args.ws)

    if args.as_json:
        print(json.dumps(result))
    else:
        label = candidate_path
        print(_fmt_result(result, label))

    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
