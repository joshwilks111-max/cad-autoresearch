# Lane 1 — `preflight.py` (sub-1s build check, no scoring)

**You are building one file: `preflight.py` at the repo root.** Pure addition. Do NOT edit `harness/`.
Repo: `C:\Users\joshw\CAD Autoresearch\cad-autoresearch`. Python: use `.venv\Scripts\python.exe`
(Python 3.13; system 3.14 breaks build123d).

## Goal
A modeler iterating on SHAPE wants <1s feedback — did it build, is it watertight, volume, bbox, face
count — WITHOUT paying the ~10-15s full grade (IoU voxelization). A full grade calls `score()`; preflight
does NOT. Confirmed separable: `run_candidate()` builds+exports+loads the mesh and returns a `RunResult`
*before any scoring* (score() is a separate call in grade_one.py:51-53).

## Exact implementation
Reuse `harness.run_candidate` (harness/runner.py:149) verbatim. Its `RunResult` (runner.py:134-146) already
carries every field: `.ok`, `.mesh` (trimesh → `.is_watertight`, `.volume`, `.bounds`), `.topology` (B-rep
dict {faces,edges,vertices,shells,solids,euler}, runner.py:107-126), `.meta` ({volume,bbox}, runner.py:94),
`.seconds`, `.error`, `.stderr`. **Never import `harness.reward` / `score`.**

CLI: `python preflight.py <candidate.py-or-.step-path> [--timeout 60] [--json] [--ws <dir>]`
Importable: `preflight(code_or_path: str, *, timeout=60, workspace=None) -> dict`.

- Read the candidate: if it ends `.py`, read its text with `encoding="utf-8"` (Windows cp1252 trap — the
  prototypes all use `Path(...).read_text(encoding="utf-8")`); if `.step`/`.stl`, you must build123d
  `import_step` then it's already a solid — but the simple v1 only needs the `.py` path (a candidate IS a
  program). Support `.py` first; `.step` optional.
- Workspace: use a UNIQUE dir per call — `tempfile.mkdtemp(prefix="preflight_")` or `runs/_preflight_<pid>`.
  **Do NOT use `runs/manual`** (shared-workspace race — two runs clobber each other's candidate.py).
- Call `run = run_candidate(code, ws, timeout=timeout)`, map fields into a dict:
  `{ok, watertight, volume, bbox, faces, edges, vertices, euler, solids, shells, seconds, error}`.
  Pull volume/bbox from `run.meta` if present (avoids recompute); faces etc from `run.topology`;
  watertight from `run.mesh.is_watertight` when `run.ok`.
- On `not run.ok`: `{ok:False, error:run.error, stderr_tail: last ~12 lines of run.stderr}`.

## Output format
Text (default):
```
PREFLIGHT  candidate.py
  ok          : True
  watertight  : True
  volume      : 2,309 mm³
  bbox (sorted): [22.0, 22.0, 7.0] mm
  faces/edges/verts : 4 / 6 / 4   (euler 2)
  solids/shells     : 1 / 1
  build       : 0.8 s
```
Failure mirrors feedback.py:83-88 (error + stderr tail). `--json` prints exactly the dict above as one line.

## Self-test (must pass, include in your report)
1. `python preflight.py tasks/bearing_608/best_candidate.py` → ok=True, watertight=True, volume≈2309,
   faces=4, build <2s.
2. A deliberately broken candidate (e.g. a temp file with `result = None`) → ok=False with a clear error.
3. Confirm `git status` shows ONLY the new `preflight.py` (no mutation of any tracked file, no runs/manual
   write). preflight is GT-free → zero leak risk.

## Report back
Files created; the two self-test outputs (paste the actual stdout); confirmed timing; any gotcha hit.
Effort: ~1-2h. It is genuinely a thin wrapper.
