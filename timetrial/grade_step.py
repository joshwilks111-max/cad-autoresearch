#!/usr/bin/env python3
"""
grade_step.py — grade a pre-existing STEP file against a reference, through the
SAME deterministic referee the AI loop uses.

This is the impartial referee for the human-vs-AI time trial (see PROTOCOL.md). The
AI competitor's build123d candidates are graded by grade_one.py with a real B-rep
topology signature computed in-sandbox; a human competitor produces a STEP, not a
program. To make the two scores commensurable, this tool grades a STEP through the
IDENTICAL path:

    import_step(step) -> build123d solid
      -> tessellate to a trimesh at a PINNED tolerance (matches the sandbox)
      -> topology_signature_from_solid(solid)         # B-rep, NOT the mesh proxy
      -> score(mesh, gt_mesh, candidate_sig=<B-rep sig>, gt_sig=<GT B-rep sig>)

Why the B-rep signature matters (the bug this tool exists to avoid): if you load a
STEP to a mesh and call score() with candidate_sig=None, topology resolves to the
mesh proxy ({components, euler, watertight}). Compared against a GT B-rep signature
({faces, edges, ...}), topology_match() returns a hardcoded NEUTRAL 0.5 on the
schema clash (geometry.py). A geometrically PERFECT human STEP would then be pinned
at topology=0.5 while the AI gets a real B-rep score — non-commensurable, and it
silently rigs the comparison. Computing the B-rep signature here fixes it.

PURE: prints only. Never writes best_candidate.py / .best_score, never touches the
shared runs/manual workspace. Re-running gives identical output and never dirties
`git status` — a verification tool must be safe to run repeatedly.

Usage:
    # grade against a registered task's hidden ground truth
    python timetrial/grade_step.py --task <task_id> --step path/to/part.step

    # bring-your-own reference (grade one STEP against another STEP)
    python timetrial/grade_step.py --ref reference.step --step mine.step

    # machine-readable
    python timetrial/grade_step.py --task <id> --step part.step --json

Exit codes: 0 = graded OK; 2 = bad usage/inputs; 3 = STEP import failed;
4 = no valid solid / no B-rep topology (non-commensurable, refused).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Pinned tessellation tolerance — MUST match the value the GT + AI sandbox use so
# Chamfer/IoU sampling noise is not a hidden variable in the comparison.
TESSELLATION_TOLERANCE = 0.05


def _err(code: int, problem: str, cause: str, fix: str, as_json: bool) -> "NoReturn":
    """Emit a problem/cause/fix error and exit with a stable code."""
    if as_json:
        print(json.dumps({"ok": False, "error": problem, "cause": cause, "fix": fix,
                          "exit": code}))
    else:
        print(f"ERROR: {problem}\n  cause: {cause}\n  fix:   {fix}", file=sys.stderr)
    sys.exit(code)


def _load_task_gt(task_id: str, as_json: bool):
    """Return (gt_mesh, gt_sig) for a registered task, or exit with guidance."""
    import yaml
    manifest_path = REPO / "tasks" / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    ids = [t["id"] for t in manifest.get("tasks", [])]
    if task_id not in ids:
        _err(2, f"task '{task_id}' is not registered",
             f"tasks/manifest.yaml has no task with id '{task_id}'",
             f"use one of: {', '.join(sorted(ids))}", as_json)
    gt_dir = REPO / "tasks" / task_id / "ground_truth"
    gt_stl = gt_dir / "result.stl"
    if not gt_stl.exists():
        _err(2, f"ground truth not built for '{task_id}'",
             f"missing {gt_stl}",
             f"run: .venv/Scripts/python.exe tasks/{task_id}/make_ground_truth.py",
             as_json)
    import trimesh
    gt_mesh = trimesh.load(str(gt_stl), force="mesh")
    gt_sig = None
    gt_topo = gt_dir / "topology.json"
    if gt_topo.exists():
        try:
            gt_sig = json.loads(gt_topo.read_text())
        except Exception:
            gt_sig = None
    return gt_mesh, gt_sig


def _step_to_mesh_and_sig(step_path: Path, label: str, as_json: bool):
    """import_step -> (trimesh mesh, B-rep topology signature). The commensurability
    fix lives here: topology comes from the SOLID (B-rep), not the mesh proxy."""
    from build123d import import_step, export_stl
    from harness import geometry as G
    import trimesh

    if not step_path.exists():
        _err(2, f"{label} STEP not found", f"no file at {step_path}",
             "check the path", as_json)
    # import
    try:
        solid = import_step(str(step_path))
    except Exception as e:
        _err(3, f"could not import {label} STEP", f"import_step raised: {e!r}",
             "export as an AP242 (or AP203) STEP, mm units, a solid body (not a "
             "surface/mesh export)", as_json)
    # B-rep topology signature from the solid (NOT the mesh proxy)
    sig = G.topology_signature_from_solid(solid)
    if not sig:
        _err(4, f"no B-rep topology from {label} STEP",
             "topology_signature_from_solid returned None (no solid / OCP unwrap "
             "failed) — grading would fall back to the mesh proxy and be "
             "non-commensurable with B-rep ground truth",
             "re-export a closed B-rep SOLID, not a surface model", as_json)
    # tessellate to a trimesh at the pinned tolerance
    ws = Path(tempfile.mkdtemp(prefix="grade_step_"))
    stl = ws / "out.stl"
    try:
        export_stl(solid, str(stl), tolerance=TESSELLATION_TOLERANCE)
        mesh = trimesh.load(str(stl), force="mesh")
    except Exception as e:
        _err(3, f"could not tessellate {label} STEP", f"export_stl raised: {e!r}",
             "the imported solid may be invalid; heal the geometry in CAD", as_json)
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        _err(4, f"{label} STEP produced an empty mesh",
             "no faces after tessellation — likely not a valid closed solid",
             "re-export a watertight solid", as_json)
    return mesh, sig, bool(getattr(mesh, "is_watertight", False))


def main():
    ap = argparse.ArgumentParser(description="Grade a STEP against a reference "
                                             "through the same B-rep referee the AI uses.")
    ap.add_argument("--step", required=True, help="the STEP file to grade")
    ap.add_argument("--task", help="registered task id whose hidden GT is the reference")
    ap.add_argument("--ref", help="a reference STEP to grade against (BYO reference)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    as_json = args.json
    if bool(args.task) == bool(args.ref):
        _err(2, "exactly one reference required",
             "pass either --task <id> (registered GT) OR --ref <ref.step> (BYO), not both/neither",
             "e.g. --task bearing_608  OR  --ref reference.step", as_json)

    from harness import score, RewardConfig

    # reference side
    if args.task:
        gt_mesh, gt_sig = _load_task_gt(args.task, as_json)
        ref_label = f"task:{args.task}"
    else:
        gt_mesh, gt_sig, _ = _step_to_mesh_and_sig(Path(args.ref), "reference", as_json)
        ref_label = f"ref:{Path(args.ref).name}"

    # candidate side (the STEP being graded)
    cand_mesh, cand_sig, watertight = _step_to_mesh_and_sig(Path(args.step), "candidate", as_json)

    rw = score(cand_mesh, gt_mesh, candidate_sig=cand_sig, gt_sig=gt_sig, cfg=RewardConfig())

    out = {
        "ok": True,
        "step": str(args.step),
        "reference": ref_label,
        "composite": rw.composite,
        "body": rw.body, "volume": rw.volume, "bbox": rw.bbox,
        "topology": rw.topology, "iou": rw.iou, "chamfer": rw.chamfer, "siou": rw.siou,
        "watertight": watertight,
        "tessellation_tolerance": TESSELLATION_TOLERANCE,
    }
    if args.json:
        print(json.dumps(out))
    else:
        print(f"composite = {rw.composite:.4f}   (reference {ref_label})")
        print(f"  body {rw.body:.0f}  volume {rw.volume:.3f}  bbox {rw.bbox:.3f}  "
              f"topo {rw.topology:.3f}  iou {rw.iou:.3f}  cham {rw.chamfer:.3f}  "
              f"siou {rw.siou:.3f}")
        if not watertight:
            print("  WARNING: candidate STEP is NOT watertight — the score may be "
                  "unreliable (heal the solid in CAD).", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
