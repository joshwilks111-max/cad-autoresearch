# Lane 5 — `regiondiff.py` (the "where am I wrong" tool — HIGHEST VALUE)

**You are building one file: `regiondiff.py` at the repo root.** Pure addition. Do NOT edit `harness/`.
Repo: `C:\Users\joshw\CAD Autoresearch\cad-autoresearch`; `.venv\Scripts\python.exe` (Python 3.13).

## Goal
The single highest-value authoring tool. The harness gives a SCALAR score; this gives an ACTIONABLE regional
correction: "volume +14% concentrated at z=120-180 (too fat); -8% at z=240-280 (too thin); 4 holes found vs
6 expected, missing near (±45,18)." Generalizes a hand-rolled per-Z-band occupancy diff (runs/_ctc05_ioucmp.py).

## VERIFIED ENV FACTS
- `scipy.ndimage.label` IS available (for connected-blob centroids).
- trimesh 4.12.2 — `voxelize(...).matrix`, `.points`, `points_to_indices`, `indices_to_points` available;
  `mesh.section(...).entities` + `.vertices` (numpy) available.
- **shapely is NOT installed** — for hole detection use `section.entities` + raw vertices ONLY. Do NOT call
  `.polygons_full`/`.area`/`.to_planar().area` (CRASH). `to_planar` deprecated → `to_2D` if needed.

## Approach (do BOTH on ONE shared voxel grid — same voxelization, ~zero marginal cost)
**Inputs:** a candidate (`.py` → `harness.run_candidate` in a UNIQUE temp ws, NOT runs/manual; or `.step`/
`.stl` → `trimesh.load`) and a reference (a task_id → `run_inner_loop.load_task`+`load_ground_truth`; or a
path). Reuse `harness.geometry._voxel_centers` (geometry.py:316) for occupancy and `_canonical_frame`
(geometry.py:196) for the `--align pca` path.

1. **Shared grid (the one subtlety):** voxelize BOTH meshes at ONE pitch over the UNION AABB so cells align.
   (My prototype voxelized each independently — fine for per-band counts, WRONG for signed cell diff.)
   Derive pitch from part size (e.g. max_extent/64, clamp ~2-6mm). Default `--align world` (candidate+GT in
   same frame, the common authoring case); `--align pca` runs both through `_canonical_frame` first.
2. **Signed cell diff:** boolean matrices Mc, Mg on the shared grid. `extra = Mc & ~Mg` (too fat / uncut hole
   / wrong-polarity boss), `missing = ~Mc & Mg` (too thin / missing feature / over-cut). Report total
   extra/missing volume %, and the centroid (world coords) of the LARGEST connected blob of each via
   `scipy.ndimage.label`.
3. **Per-axis-band profile:** pick the long axis (PCA or largest extent), bin into ~12 bands, report signed
   Δ% per band; flag bands where |Δ| exceeds an adaptive threshold (prototype used
   `abs(nc-ng) > max(40, 0.25*max(ng,1))` — keep that).
4. **Holes:** `mesh.section` at a few heights (e.g. long-axis 0.2/0.5/0.8). Count inner loops (a loop is a
   hole if `r_std/r_mean` small); report centroid+radius per hole. Diff candidate vs GT hole sets by nearest
   centroid → "missing N near (x,y), extra M near (x,y)". For dense fields (CTC-05's 29 holes) report counts
   per band, don't enumerate all.

## Output format (THIS IS THE PRODUCT — terse, ends with one imperative correction line)
```
REGIONDIFF  cand=candidate.py  ref=trial_lbracket   pitch=4.0mm  axis=Z(long, 44mm)
vol: cand 14.4M vs GT 12.7M  (+13.6% over)   bbox cand[120,60,44] vs GT[120,60,44] OK
─ material by Z-band (Δ = cand−GT, % of band) ─
  z 8–20    +14%  TOO FAT  (extra blob ctr ≈ (250,12,15))
  z 30–40    −8%  too thin
─ holes (section count @ z=12/22/40) ─
  found 4, GT has 6  → MISSING 2 near (±45,18) r≈4;  extra 0
OVERALL: trim ~14% material around z=8-20; add 2 holes near (±45,18); ~8% thin at z=30-40.
```
CLI: `python regiondiff.py --cand <path> --ref <task_id-or-path> [--pitch N] [--bands 12] [--axis auto|x|y|z] [--align world|pca] [--holes section|off]`. Importable: `regiondiff(cand_mesh, ref_mesh, ...) -> RegionDiff` (dataclass w/ `.text` + structured fields).

## Self-test (must pass, include in report)
1. Self-diff: grade `tasks/bearing_608/best_candidate.py` against ref `bearing_608` → near-zero deltas
   everywhere, holes found==GT (a part vs itself = "no correction needed"). Paste output.
2. A deliberately-wrong candidate: take bearing_608 but change bore radius 4→6 → regiondiff should report
   the bore region as having extra/missing material. Paste output.
3. `git status` shows only the new `regiondiff.py`.

## Report back
File created; both self-test outputs (paste stdout); confirm the shared-grid alignment works; note the
GT-LEAK caveat (output reveals GT — fine grader-side / interactive, never feed into a worker's spec on a
drawing-track task). Effort ~0.5-1 day. Highest leverage of all lanes.
