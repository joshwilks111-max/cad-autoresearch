# Lane 3 — through-hole discriminator (new grading signal)

**You are building one file: `harness_ext/holes.py` (a NEW module, NOT inside harness/).** Put it at repo
root as `hole_metrics.py` to be safe — do NOT edit `harness/`. Repo:
`C:\Users\joshw\CAD Autoresearch\cad-autoresearch`; `.venv\Scripts\python.exe` (Python 3.13).

## Goal
The reward is blind to through-vs-blind holes and under-weights missing holes (documented: a hole-less box
scores ~0.99 on surface layers). Build a tiny tool that, for a mesh, counts THROUGH holes vs BLIND holes by
ray-casting. No published benchmark scores this — it's a genuine new engineering signal. ~30-60 LOC.

## VERIFIED ENV FACT
`trimesh` mesh `.ray.intersects_location` IS present (tested on a real GT mesh). `mesh.contains(points)`
works for watertight meshes (no embree needed).

## Approach (mesh-based, kernel-agnostic — works on any STL/STEP-derived mesh)
The robust, simple version (do this — it does not need B-rep cylinder faces):
1. Voxel/grid the part's bounding region OR sample candidate hole-axis directions. Simplest reliable v1:
   detect cylindrical negative space via **section-loop counting** (the shapely-free pattern — see below)
   at several heights, get each inner-loop centroid + radius + the axis (section normal).
2. For each candidate hole (centroid c, axis direction d): cast a ray from a point just outside the part
   along the bore axis through c. Count solid entries/exits via `mesh.ray.intersects_location`. A THROUGH
   hole: the ray passes fully through open space bounded by material on both sides AND exits the far side
   (the bore connects two outer faces). A BLIND hole: the bore terminates inside material (ray hits a floor).
   Concretely: sample points along the bore axis inside the hole radius; `mesh.contains` is False through
   the full thickness for a through hole, but True (material) past some depth for a blind hole.
3. Return `{n_holes, n_through, n_blind, holes:[{center,radius,axis,kind}]}`.

**shapely-free hole detection (CRITICAL — shapely is NOT installed):** use
`mesh.section(plane_origin=o, plane_normal=n)` → `section.entities` (each = one closed loop) and
`section.vertices[entity.points]` (numpy). Outer boundary = 1 loop; each inner loop at that height = a hole.
A loop is circular if `r_std/r_mean` is small (compute radii from the loop's vertices about its centroid).
**Do NOT call `.polygons_full`, `.area`, `.to_planar().area`, `.polygons_closed`** — they import shapely and
CRASH. (The repo's `runs/_aa_loops.py` / `_aa_bores.py` show the correct numpy-only pattern;
`runs/_ctc05_diag.py:38`'s `planar.area` is BROKEN in this env — do not copy it.) `to_planar` is also
deprecated → if you need 2D use `to_2D`, but you can work in 3D section coords.

## Interface
CLI: `python hole_metrics.py <candidate.py-or-.step> [--json] [--sections 0.2,0.5,0.8]`
Importable: `hole_metrics(mesh, section_fracs=(0.2,0.5,0.8)) -> dict`.
To get a mesh from a `.py`: reuse `harness.run_candidate` (returns RunResult.mesh) in a unique temp ws
(NOT runs/manual). From a `.step`: `trimesh.load(path, force="mesh")`.

## Self-test (must pass, include in report)
1. `tasks/bearing_608/ground_truth/result.stl` (a Ø8 bore through a Ø22 ring, 7mm thick) → n_holes≥1,
   the bore classified THROUGH. Paste the output.
2. A blind-hole test: build `Box(40,40,20).cut(Cylinder(r=5,h=10) placed to NOT reach the far face)` →
   the hole classified BLIND. (If section-counting is flaky on this, document it honestly.)
3. `git status` shows only the new `hole_metrics.py`.

## Report back
Files created; both self-test outputs; HONEST note on accuracy (this is heuristic — say where it's reliable
vs flaky). Do NOT wire it into reward.py in this lane (that's a separate decision) — just build the standalone
metric + note how it WOULD integrate (a hole-count term keyed on GT hole count). Effort ~2-3h.
