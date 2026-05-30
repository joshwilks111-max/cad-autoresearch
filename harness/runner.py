"""
runner.py — execute a candidate CAD program in an isolated sandbox.

A "candidate" is a Python script (written by an agent or the mock proposer) that
builds a part and assigns the final solid to a module-level variable named
`result`. Both build123d (Part / Solid / BuildPart context) and CadQuery
(Workplane) are supported. The script runs in a SEPARATE PROCESS with a wall-clock
timeout, so an infinite loop, a kernel segfault, or a runaway allocation degrades
to a graded failure instead of killing the worker.

The sandbox epilogue, appended to every candidate, resolves `result` into a
solid, exports result.step + result.stl, and writes meta.json (volume, bbox) and
topology.json (B-rep counts). The B-rep signature is computed INSIDE the sandbox
because OpenCASCADE objects cannot be pickled back to the parent process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

import trimesh


_SANDBOX_EPILOGUE = textwrap.dedent(
    '''
    # --- autoresearch sandbox epilogue (auto-appended) ---------------------
    def __ar_export():
        import json as _json, os as _os
        g = globals()
        obj = g.get("result", None)
        if obj is None:
            raise RuntimeError("candidate did not define a variable named 'result'")

        solid = obj
        if hasattr(obj, "part") and not hasattr(obj, "wrapped"):
            solid = obj.part                      # build123d BuildPart context
        if obj.__class__.__name__ == "Workplane":
            try:
                solid = obj.val()                 # CadQuery
            except Exception:
                pass

        out = _os.environ["AR_WORKSPACE"]
        step_path = _os.path.join(out, "result.step")
        stl_path = _os.path.join(out, "result.stl")

        exported = False
        try:
            from build123d import export_step as _es, export_stl as _et
            _es(solid, step_path); _et(solid, stl_path, tolerance=0.05); exported = True
        except Exception:
            pass
        if not exported:
            try:
                import cadquery as _cq
                _cq.exporters.export(obj, step_path)
                _cq.exporters.export(obj, stl_path, tolerance=0.05)
                exported = True
            except Exception as e:
                raise RuntimeError("export failed: %r" % e)

        meta = {}
        try:
            meta["volume"] = float(abs(solid.volume))
        except Exception:
            meta["volume"] = None
        try:
            bb = solid.bounding_box()
            meta["bbox"] = [float(bb.size.X), float(bb.size.Y), float(bb.size.Z)]
        except Exception:
            meta["bbox"] = None
        with open(_os.path.join(out, "meta.json"), "w") as f:
            _json.dump(meta, f)

        sig = None
        try:
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopAbs import (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX,
                                    TopAbs_SHELL, TopAbs_SOLID)
            w = getattr(solid, "wrapped", solid)
            def _c(kind):
                e = TopExp_Explorer(w, kind); s = set()
                while e.More():
                    s.add(e.Current().__hash__()); e.Next()
                return len(s)
            _f = _c(TopAbs_FACE); _e = _c(TopAbs_EDGE); _v = _c(TopAbs_VERTEX)
            sig = {"faces": _f, "edges": _e,
                   "vertices": _v, "shells": _c(TopAbs_SHELL),
                   "solids": _c(TopAbs_SOLID),
                   "euler": _v - _e + _f}   # Euler characteristic (matches grader)
        except Exception:
            sig = None
        with open(_os.path.join(out, "topology.json"), "w") as f:
            _json.dump(sig, f)

    __ar_export()
    print("AR_EXPORT_OK")
    '''
)


@dataclass
class RunResult:
    ok: bool
    workspace: Path
    step_path: Path | None = None
    stl_path: Path | None = None
    mesh: object | None = None            # trimesh.Trimesh
    topology: dict | None = None
    meta: dict = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    seconds: float = 0.0


def run_candidate(code: str, workspace: str | Path, timeout: int = 120,
                  python: str | None = None) -> RunResult:
    """Run `code` in `workspace`; return artifacts + a loaded mesh."""
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    script = ws / "candidate.py"
    script.write_text(code + "\n" + _SANDBOX_EPILOGUE)

    full_env = {**os.environ, "AR_WORKSPACE": str(ws), "PYTHONUNBUFFERED": "1"}

    t0 = time.time()
    try:
        proc = subprocess.run(
            [python or sys.executable, str(script)],
            capture_output=True, text=True, timeout=timeout,
            env=full_env, cwd=str(ws),
        )
    except subprocess.TimeoutExpired as e:
        return RunResult(ok=False, workspace=ws, error=f"timeout after {timeout}s",
                         stdout=e.stdout or "", stderr=e.stderr or "",
                         seconds=time.time() - t0)
    secs = time.time() - t0

    if proc.returncode != 0 or "AR_EXPORT_OK" not in proc.stdout:
        return RunResult(ok=False, workspace=ws,
                         error=f"candidate exited {proc.returncode}",
                         stdout=proc.stdout, stderr=proc.stderr, seconds=secs)

    step_path = ws / "result.step"
    stl_path = ws / "result.stl"
    try:
        mesh = trimesh.load(str(stl_path), force="mesh")
    except Exception as e:
        return RunResult(ok=False, workspace=ws, error=f"stl load failed: {e!r}",
                         stdout=proc.stdout, stderr=proc.stderr, seconds=secs)

    def _read_json(p):
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except Exception:
            return None

    return RunResult(ok=True, workspace=ws,
                     step_path=step_path if step_path.exists() else None,
                     stl_path=stl_path, mesh=mesh,
                     topology=_read_json(ws / "topology.json"),
                     meta=_read_json(ws / "meta.json") or {},
                     stdout=proc.stdout, stderr=proc.stderr, seconds=secs)
