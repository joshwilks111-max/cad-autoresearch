# Lane 6 — `perceive.py` (let a blind agent SEE the candidate vs reference)

**You are building one file: `perceive.py` at the repo root.** Pure addition. Do NOT edit `harness/` (but you
MAY import from `harness/render.py`). Repo: `C:\Users\joshw\CAD Autoresearch\cad-autoresearch`;
`.venv\Scripts\python.exe`.

## Goal
An agent iterating on a scalar score is effectively blind. Give it perception two ways: (a) an ASCII
silhouette diff (the ONLY thing a text-only agent can consume — ~600 chars, in-band) and (b) a single
overlay PNG (richest for a VLM — cand+GT superimposed, diff highlighted). Build both on one projection core.

## VERIFIED ENV FACTS
- matplotlib 3.10.9 with Agg backend (harness/render.py:15 already uses `matplotlib.use("Agg")`).
- `scipy.spatial.cKDTree` is imported in geometry.py:17 (use for signed-distance diff coloring).
- shapely NOT installed (irrelevant here — you project meshes, no 2D boolean).

## Approach
**Inputs:** same resolver as Lane 5 — candidate (`.py`→run_candidate in unique temp ws; or `.step`/`.stl`),
reference (task_id→load_ground_truth; or path).

### (a) ASCII silhouette diff — primary for text agents
Project both meshes onto a view plane (drop one axis per view: front=drop Y, top=drop Z, right=drop X).
Rasterize each to a boolean mask on a small char grid (default 64×32) by binning surface points
(`harness.geometry.sample_surface`, geometry.py:57, or voxel `.points`). Overlay with 3 symbols:
`#`=both, `+`=cand-only (too fat), `·`=GT-only (missing). Print a 2D-IoU per view + a "lowest IoU view →
look there" pointer.
```
PERCEIVE  cand vs trial_lbracket   view=front   grid=64x32   2D-IoU=0.86
  # both   + cand-only   · GT-only
     ############
   ##############++++      ← cand bulges right
   ##····########            ← GT hole cand filled
2D silhouette IoU  front 0.86  top 0.91  right 0.79   (lowest: right — look there)
```

### (b) overlay PNG — primary for VLM agents
ONE figure, 3 columns (front/top/right or iso). Reuse render.py machinery: `matplotlib.use("Agg")`, the
`_VIEWS` dict (render.py:20), `ax.plot_trisurf` (render.py:29), centre/limits/box-aspect (render.py:32-37).
KEY difference from `render_compare`: draw BOTH meshes in the SAME axes — GT as low-alpha gray, candidate
colored. Bonus: color candidate faces by signed distance to GT surface via `cKDTree` (red=protruding/extra,
blue=recessed/missing). Decimate huge meshes (`mesh.simplify_quadric_decimation` if >~20k faces) to stay
<1s. Output ~0.3MB at dpi=90.

CLI: `python perceive.py --cand <path> --ref <task_id-or-path> [--ascii|--png|--both] [--view front|top|right|iso|all] [--grid 64x32] [--out runs/_perceive_<pid>]`. Importable: `ascii_diff(cand_mesh, ref_mesh, view="front", grid=(64,32)) -> str`; `overlay_png(cand_mesh, ref_mesh, out_dir, views=(...)) -> list[str]`. Default `--ascii` (works everywhere); `--png` adds the overlay.

## Self-test (must pass, include in report)
1. `python perceive.py --cand tasks/bearing_608/best_candidate.py --ref bearing_608 --ascii` → mostly `#`
   (part vs itself ≈ full overlap), high 2D-IoU. Paste the ASCII output.
2. `--png` on the same → writes 1 PNG; confirm it exists + size. (You can't see it, but confirm it rendered
   without error.)
3. A wrong candidate (bore 4→6 like Lane 5) → ASCII shows `·`/`+` divergence at the bore. Paste it.
4. `git status` shows only the new `perceive.py`.

## Report back
File created; the ASCII self-test outputs (paste); PNG render confirmed; note the GT-LEAK caveat (same as
render_compare — never feed into a worker's spec on a drawing-track task). Effort ~0.5 day (ASCII ~2h,
overlay PNG ~2h since render.py does the heavy lifting).
