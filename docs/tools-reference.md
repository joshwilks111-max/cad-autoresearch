# Tools reference — grader-side & authoring tools

Reference for the 8 standalone Python tools at the **repo root** (not inside `harness/`).
Audience: a future coding session improving the harness who needs to *use* these tools.
This is a Diátaxis **reference** doc — look up a tool, copy the exact invocation, heed the
caveats. For the *why* behind the scores read [known-limitations.md](known-limitations.md);
for the layer mechanics read [ARCHITECTURE.md](ARCHITECTURE.md).

## What these are (and are not)

These 8 files are **pure additions at the repo root** — grader-side / authoring tools, not
part of the core six-layer reward. None of them is imported by `harness/reward.py`,
`run_inner_loop.py`, or the orchestrator; the scoring path does not depend on them. They
**import from `harness/` read-only** (`harness.runner.run_candidate`, `harness.geometry`
helpers) and never mutate harness state. Each builds a candidate in a **unique temp
workspace** (`tempfile.mkdtemp(...)`), never `runs/manual/` — so they are safe to run
concurrently with a live grid (no shared-workspace race).

Run them with the project venv: `.venv/Scripts/python.exe <tool>.py ...` (Windows). The
candidate contract is the same as the harness: a `.py` candidate assigns its solid to a
module-level `result`; the sandbox appends the export/grade epilogue.

### GT-leaking vs candidate-only-safe (READ THIS)

Some tools compare the candidate against the hidden ground truth, so **their output reveals
GT geometry**. They are for **grader-side / interactive use only**. Never paste their output
into a worker's spec, feedback report, or a drawing-track prompt — doing so hands the agent
the answer and invalidates the run.

The **Verdict** column is a keep/retire call (`core` = load-bearing, keep; `optional` =
useful but niche; `retire` = superseded — none currently). It is the Software-3.0
"Foxconn audit": each tool earns its place or gets a flag. Verdicts reflect the dogfood
findings (see `research-and-deferred.md` + the project memory updates).

| Tool | Verdict | GT-leaking? | Why |
|------|---------|-------------|-----|
| `preflight.py`        | **core**     | **Safe (candidate-only)** | Sub-3s build+sanity gate — the authoring workbench's front door; no reference. |
| `occ_guard.py`        | **core**     | **Safe (candidate-only)** | Guards the real OCC silent-empty/fragment boolean traps; no reference. |
| `unit_normalize.py`   | **core**     | **Safe (candidate-only)** | Makes the recurring inch→mm bug architecturally impossible. Pure data transform. |
| `drawing_extract.py`  | **core**     | **Safe (candidate-only)** | The `drawing-read` pack's engine. Reads the *given* drawing (an input), not GT. |
| `regiondiff.py`       | **core**     | **GT-LEAKING**            | The dogfood-proven "where am I wrong" tool — signed cell/band/hole diff vs the reference. |
| `perceive.py`         | **optional** | **GT-LEAKING**            | Silhouette/overlay diff vs the reference; handy for VLM overlays, ASCII path is niche. |
| `hole_metrics.py`     | **optional** | Safe candidate-only / **GT-leaking with `--ref`-style use** | Through-vs-blind discriminator; has a known thin-feature residual, and `surface_histogram` covers more topology. Safe alone; leaking if run on the GT mesh and fed back. |
| `surface_histogram.py`| **core**     | Safe candidate-only / **GT-leaking with the GT histogram** | Kernel-stable surface-type topology — the one with a pending `reward.py` integration. Safe alone; `histogram_similarity(hc, hg)` against a GT histogram leaks. |

---

## `preflight.py` — fast build + sanity check (no scoring)

**Purpose:** sub-second "did the candidate build and is it geometrically sane" check —
watertight / volume / bbox / topology counts, with **no IoU or reward** computed. Reuses
`harness.runner.run_candidate` verbatim; never imports `harness.reward`.

**CLI**
```
python preflight.py <candidate.py> [--timeout 60] [--json] [--ws DIR]
```
- `<candidate>` (positional, required) — path to a candidate `.py` (or `.step`).
- `--timeout` — subprocess build timeout in seconds (default `60`).
- `--json` — print the result dict as a single JSON line (otherwise human-readable).
- `--ws DIR` — workspace directory to preserve artifacts (default: unique temp dir, auto-cleaned).

Exit code is `0` if the build is `ok`, `1` otherwise.

**Importable API**
```python
from preflight import preflight
preflight(code_or_path: str, *, timeout: int = 60, workspace: str | None = None) -> dict
```
`code_or_path` accepts either a path to a `.py` file **or** raw source text. Returns a dict
with keys: `ok, watertight, volume, bbox, faces, edges, vertices, euler, solids, shells,
seconds, error` (on failure: `ok=False, error, stderr_tail`).

**Example**
```bash
.venv/Scripts/python.exe preflight.py candidate.py --json
# {"ok": true, "watertight": true, "volume": 31337.0, "bbox": [20.0, 30.0, 50.0],
#  "faces": 11, "edges": 27, "vertices": 18, "euler": 2, "solids": 1, "shells": 1, ...}
```

**Known limitations / caveats**
- The result key is **`vertices`**, not `verts` (the human-readable printout labels it
  `faces/edges/verts` but the dict/JSON key is `vertices`).
- `bbox` is returned **sorted ascending** for canonical display, so it is *not* axis-labelled
  (you cannot read off which dimension is X/Y/Z from it).
- `volume`/`bbox` come from `run.meta` (computed inside the sandbox) and `watertight` from the
  loaded trimesh; any of these can be `None` if the sandbox didn't populate them (older
  candidate or partial failure) — handle `None` before formatting.
- It deliberately does **not** score. A candidate that passes preflight can still be a poor
  reconstruction (wrong shape, wrong holes). Use it as a cheap gate before the full grade,
  not as a substitute for it.
- No `--selftest`; passing raw source via the *CLI* isn't supported (the positional is treated
  as a path) — use the importable API for inline source.

---

## `occ_guard.py` — loud-fail guardrails for build123d / OCP booleans

**Purpose:** wrap the boolean/fillet/revolve operations that **silently** return garbage on
OCP/OCC 7.8 (`IsDone()=True` on empty or fragmented solids; `HasErrors`/`HasWarnings` are
**not exposed** in this OCP build — verified `hasattr(op,'HasErrors') == False`). Each wrapper
raises a `ValueError` with an actionable message instead of letting bad geometry through to
the grader. Detection uses a **volume + solid-count proxy** since the OCC error flags are
unavailable.

**CLI (self-test only)**
```
python occ_guard.py
```
Runs `_selftest()` and exits non-zero on any failure. Note: `__main__` calls the self-test
directly and **ignores argv** — there is no real argument parser, so `--selftest` happens to
work only because the flag is swallowed. The canonical invocation is the bare command above.

**Importable API**
```python
from occ_guard import (
    safe_cut, safe_fuse, safe_intersect,   # boolean wrappers
    safe_fillet, check_revolve_profile, validate_solid,
)

safe_cut(base, *tools, label="cut")           -> Shape   # gates empty/zero-vol + fragmentation
safe_fuse(base, *tools, label="fuse")         -> Shape   # gates empty/zero-vol + fragmentation
safe_intersect(base, *tools, label="intersect") -> Shape # gates empty/zero-vol ONLY
safe_fillet(solid, edges, radius, label="fillet") -> Solid  # raw BRepFilletAPI + IsDone check
check_revolve_profile(pts_2d, axis_x=0.0)     -> None    # raises if profile crosses the axis
validate_solid(solid, label="final")          -> None    # raises if empty; warns if not is_valid
```

**Example**
```python
from build123d import Box, Cylinder
from occ_guard import safe_cut
result = safe_cut(Box(20, 20, 20), Cylinder(radius=5, height=30))  # through-bore; OK
# A boolean that shatters the body raises:
#   ValueError: [cut] result fragmented into 3 disjoint solids (base had 1) ...
```

**Known limitations / caveats**
- **The boolean gate fires on two signals only:** (1) empty / zero-volume result
  (`n_solids == 0 or volume <= 1e-9`), and (2) **fragmentation** — the result has *more*
  disjoint solids than the base started with. It does **NOT** reject large material removal.
  An earlier version gated on ">50% volume collapse"; that **falsely rejected valid large
  cuts** (hollowing, shelling, big pockets routinely remove >50% and are correct) and **was
  fixed in review**. The gate is on topology (did it shatter?), not on how much was removed.
- `safe_intersect` skips the fragmentation check (`pre_solids=None`): intersections legitimately
  produce a different solid count than the base, so only the empty/zero-volume gate applies.
- `safe_fillet` uses raw `BRepFilletAPI_MakeFillet` and **can** check `IsDone()` — fillets *do*
  expose a real success flag (unlike `BRepAlgoAPI_Cut`). It also gates on `volume > 0` in case
  `IsDone` lies.
- `check_revolve_profile` is pure numpy (no shapely — shapely is **not installed** in this env).
  It only checks **axis crossing**; it does not catch every self-intersection (e.g. a profile
  that self-overlaps without crossing the revolve axis).
- `validate_solid` **warns** (does not raise) when `solid.is_valid` is `False` — the geometry
  may still export; consider `.fix()` before relying on it.

---

## `hole_metrics.py` — through-hole / blind-hole discriminator

**Purpose:** count holes in a mesh by cross-section loop analysis (shapely-free) and classify
each as **THROUGH** or **BLIND** via bore-axis sampling with `mesh.contains()`.

**CLI**
```
python hole_metrics.py <mesh_or_candidate.py> [--json] [--sections 0.2,0.5,0.8]
```
- `<mesh>` (positional, required) — path to `.stl`/`.step`/`.stp` **or** a candidate `.py`.
- `--json` — output JSON (indented).
- `--sections` — comma-separated section fractions. **Default `None` = dense auto-placement**
  (~every 4 mm per axis). Pass e.g. `0.2,0.5,0.8` to override with fixed fractions.

**Importable API**
```python
from hole_metrics import hole_metrics
hole_metrics(mesh: trimesh.Trimesh,
             section_fracs: Sequence[float] | None = None,
             circ_threshold: float = 0.15) -> dict
```
Returns `{n_holes, n_through, n_blind, holes}` where `holes` is a list of
`{center, radius, axis, kind, r_std}` (`kind` ∈ `"through" | "blind"`, `axis` ∈ `"X"|"Y"|"Z"`).
The API takes an already-loaded `trimesh.Trimesh`; the CLI's `_load_mesh` handles `.py`/`.step`
loading for you.

**Example**
```bash
.venv/Scripts/python.exe hole_metrics.py candidate.py --json
# {"n_holes": 4, "n_through": 4, "n_blind": 0, "holes": [
#    {"center": [45.0, 18.0, 4.0], "radius": 2.5, "axis": "Z", "kind": "through", "r_std": 0.01}, ...]}
```

**Known limitations / caveats**
- **Axis-aligned bores only.** Reliable only for cylindrical holes whose axis is aligned with
  one of the three principal axes (X/Y/Z), detected via Z/Y/X cross-sections. **Angled / helical
  holes are NOT detected.**
- **≥2-plane confirmation:** a candidate bore is accepted only if it appears on **≥2 section
  planes of the same axis** (`hits >= 2`). This drops single-plane phantoms (junction/corner
  loops that sneak under the circularity gate) but means a bore so short it is sliced by only
  one plane can be missed. Section placement is dense (~4 mm spacing, `max_planes=64`) over the
  interior 5%–95% of each axis.
- **Circularity gate `cv = r_std/r_mean < 0.15`:** may miss very coarse-meshed cylinders (a
  faceted bore reads as non-circular) or, on very fine meshes, occasionally admit a near-circular
  rectangular notch.
- **Blind classification is definitive; through is not.** If *any* sample point inside the bore
  is material (`contains == True`), the hole is BLIND. THROUGH classification can be **fooled by
  walls thinner than the sample step** — a very thin wall reads as air and the hole looks through.
- **Thin-wall-parallel-to-deep-axis undercount:** the canonical landmine. On a part where the
  through-holes run *across* a thin dimension while the part is deep along another axis,
  `trimesh.section` does **not** return those bores as closed loops on the deep-axis planes, so
  some are not counted (the documented cap is ~4 of 6 holes on such a part). This is the same
  mesh-sectioning limitation `regiondiff` hits — for those parts a B-rep cylinder-face count is
  the right tool, not mesh sectioning.

---

## `unit_normalize.py` — unit detection + mm normalization

**Purpose:** deterministically detect drawing units and convert all dimension/tolerance values
to mm **before** any value reaches build123d. This makes the recurring inch→mm bug
*architecturally impossible*. **Importable-only — no CLI.**

**Importable API**
```python
from unit_normalize import detect_units, normalize_to_mm

detect_units(*, title_block_text: str = "", explicit: str | None = None,
             dimension_values: list[float] | None = None,
             part_category: str | None = None) -> tuple[str, str]   # (units, source)

normalize_to_mm(extracted: dict) -> dict   # mutates in place; idempotent
```
`detect_units` returns `(units, source)` with `units ∈ {'mm','in','unknown'}` via a 3-tier
heuristic: **Tier 1** keyword / tolerance-note scan of the title block (or an `explicit`
override), **Tier 2** magnitude inference (median |dim| < 12 → in; > 15 → mm; 12–15 →
`unknown`), **Tier 3** `part_category` prior (`us/aerospace/asme` → in; `iso/european` → mm).

`normalize_to_mm` scales every recognised linear field by 25.4 **only when `units == 'in'`**,
then sets `units='mm'` and `conversion_applied=True`.

**Example**
```python
from unit_normalize import detect_units, normalize_to_mm
detect_units(title_block_text="UNLESS OTHERWISE SPECIFIED ±0.005 IN")   # -> ('in', 'tolerance_note')
d = {"units": "inch", "features": [{"diameter_mm": 0.5, "depth_mm": 1.0}]}
normalize_to_mm(d)
# d["units"] == "mm", d["conversion_applied"] is True, diameter_mm == 12.7, depth_mm == 25.4
```

**Known limitations / caveats**
- **Idempotent via `conversion_applied`:** if that flag is already `True`, the dict is returned
  **unchanged regardless of the `units` field** — never double-scales, but also means you must
  not hand-set `conversion_applied=True` on un-normalized data.
- **Inch aliases are case-insensitive:** `{in, inch, inches, in., ", imperial}` all convert. A
  bare `units != "in"` check elsewhere would let `"inch"`/`"INCH"` escape — that was the exact
  bug this tool exists to prevent (caught in review). Anything not in the alias set (incl.
  `'unknown'`) is treated as already-mm and **not** scaled.
- **Field matcher is an allowlist + denylist, not "scale every number."** It converts
  `*_mm`, `nominal`, `diameter`, `depth`, `radius`, `tolerance`, and word-boundary tolerance
  tokens (`*_tol`, `_tol_`, `tol_*`). It **excludes** angular fields (`*angle*`, `*deg*` — degrees
  must never be ×25.4) and categoricals/counts (`*_class`, `*_grade`, `*_count`, `quantity`,
  `*_qty`). A length field with a non-matching name (e.g. `length`, `width`, `od`) will be
  **silently left in inches** — extend `_is_numeric_dim_field` if your schema adds such fields.
- Recurses into nested `dict`s and into `dict` elements of lists; scalars at the top level are
  matched too. Plain numeric lists (not lists-of-dicts) are not scaled.

---

## `regiondiff.py` — "where am I wrong" regional correction

**Purpose:** turn the scalar reward into an **actionable regional** diff. On one shared voxel
grid it produces three things at ~zero marginal cost: (1) **signed cell diff** (extra/missing
volume % + world centroid of the largest connected blob of each), (2) **per-axis-band material
delta** along the long axis, (3) **multi-axis hole diff** (count + which bores are
missing/extra/wrong-radius). The product is a terse text report ending in one imperative
correction line.

**CLI**
```
python regiondiff.py --cand <path> --ref <task_id-or-path>
    [--pitch N] [--bands 12] [--axis auto|x|y|z] [--align world|pca]
    [--holes section|off] [--build-timeout 120]
```
- `--cand` (required) — candidate `.py` / `.step` / `.stl`.
- `--ref` (required) — a **task_id** (loads the hidden GT) **or** a path to a `.step`/`.stl`.
- `--pitch` — voxel pitch mm (default: `max_extent/64` clamped to 2–6 mm).
- `--bands` — number of long-axis bands (default `12`).
- `--axis` — `auto|x|y|z` (default `auto` = longest extent of the reference).
- `--align` — `world|pca` (default `world`; see caveat).
- `--holes` — `section|off` (default `section`).
- `--build-timeout` — candidate build timeout in seconds (default `120`). *(Not in the original
  tool description but present in the CLI.)*

**Importable API**
```python
from regiondiff import regiondiff, RegionDiff
regiondiff(cand_mesh: trimesh.Trimesh, ref_mesh: trimesh.Trimesh,
           pitch: float | None = None, bands: int = 12,
           axis: str = "auto", align: str = "world",
           holes: str = "section", cand_label: str = "candidate",
           ref_label: str = "ref") -> RegionDiff
```
Returns a `RegionDiff` dataclass; `str(rd)` / `rd.text` is the terse report. Structured fields
include `vol_delta_pct, extra_vol_pct, missing_vol_pct, extra_blob_center, missing_blob_center,
bands` (list of `BandDiff`), `holes_found/holes_expected`, `missing_holes/extra_holes/resized_holes`,
and `notes`. The importable API takes **already-loaded meshes** — the CLI's loaders handle
`.py`/`.step`/task_id resolution.

**Example**
```bash
.venv/Scripts/python.exe regiondiff.py --cand candidate.py --ref ftc_09
# REGIONDIFF  cand=candidate.py  ref=ftc_09  pitch=3.1mm  axis=Z(long, 44mm)  align=world
# vol: cand 28.1k vs GT 31.0k  (-9.4% under)  bbox cand[...] vs GT[...] OK
# cells: extra(cand-only) 2.1% of GT vol @blob~(...); missing(GT-only) 11.3% @blob~(...)
# ─ holes (all-axis section @ frac 0.2/0.5/0.8) ─
#   found 4, GT has 6  → MISSING 2 near (45,18,4) r≈2.5; ...
# OVERALL: add ~11% material around Z=30-44; add 2 hole(s) near (45,18,4) r≈2.5.
```

**Known limitations / caveats**
- **GT-LEAK:** the report reveals ground-truth geometry (volumes, band deltas, exact hole
  positions/radii). Use it **grader-side or interactively only**. **Never** feed regiondiff
  output into a worker's spec/feedback on a drawing-track task — it hands the agent the answer.
- **`align='world'` is the default and usually correct.** In the harness the candidate and GT
  are already co-located, so `world` diffs cleanest. `align='pca'` brings both into a shared
  PCA frame (GT-derived rotation + a 48-transform sign/permutation search on the candidate) for
  the case where pose differs — but it can only resolve orientation **up to symmetry** and adds
  voxel noise. On a rotationally-symmetric part or when post-align IoU < 0.6 it emits a
  `PCA ALIGN UNRELIABLE` note and the band/hole diff may be dominated by residual pose, not real
  shape error. Prefer `world` unless you know the frames differ.
- **Hole detection shares `hole_metrics`'s mesh-sectioning limits.** Same dense ~4 mm planes,
  `max_planes=64`, ≥2-plane per-axis confirmation, and `cv < 0.15` circularity gate. The same
  thin-wall-parallel-to-deep-axis undercount applies: `trimesh.section` does not return those
  bores as closed loops, so a part can report e.g. **4 of 6** holes. Don't trust the hole count
  as ground truth on such parts.
- **Dense hole fields are not enumerated.** If either side has >8 holes the report switches to
  counts-only ("dense field"), so you get `found N, GT has M` but not per-hole positions.
- **Non-watertight candidates** fall back from `mesh.contains` to a voxelise-and-rasterise path;
  occupancy is then approximate (voxel-grid quantised), which can add a little phantom
  extra/missing volume.

---

## `perceive.py` — silhouette diff (text) + overlay PNG (VLM)

**Purpose:** give a "blind" agent perception of candidate vs reference. Two outputs: (a) an
**ASCII silhouette diff** for text-only agents (in-band, no files), and (b) an **overlay PNG**
for VLM agents (GT in gray + candidate colored by signed distance to the GT surface).

**CLI**
```
python perceive.py --cand <path> --ref <task_id-or-path>
    [--ascii | --png | --both] [--view front|top|right|iso|all]
    [--grid 64x32] [--out DIR] [--selftest]
```
- `--cand` — candidate `.py` / `.step` / `.stl` (required unless `--selftest`).
- `--ref` — task_id **or** a path to a reference `.stl`/`.step` (required unless `--selftest`).
- `--ascii` / `--png` / `--both` — output mode. **Default (none given) = ASCII.**
- `--view` — `front|top|right|iso|all` (default `all` = three orthographic views).
- `--grid` — ASCII raster size `WxH` (default `64x32`).
- `--out` — output directory for PNGs (default `runs/_perceive_<pid>`).
- `--selftest` — GT-free self-test (bearing-vs-itself; reads no task GT).

**Importable API**
```python
from perceive import ascii_diff, overlay_png
ascii_diff(cand_mesh, ref_mesh, view="front", grid=(64, 32)) -> str
overlay_png(cand_mesh, ref_mesh, out_dir, views=("front","top","right")) -> list[str]
```
ASCII symbols: `#` = both present, `+` = candidate-only (too fat), `·` = GT-only (missing),
space = neither; each view's header carries a 2D-IoU. (`ascii_diff(view="all")` and the helper
`ascii_diff_all_views` concatenate the three views and flag the lowest-IoU one.) The importable
API takes **already-loaded meshes**.

**Example**
```bash
.venv/Scripts/python.exe perceive.py --cand candidate.py --ref bearing_608 --ascii --view front
# PERCEIVE  view=FRONT   grid=64x32   2D-IoU=0.97
#   # both   + cand-only   · GT-only
#   ...silhouette...
.venv/Scripts/python.exe perceive.py --cand candidate.py --ref bearing_608 --png   # writes overlay_*.png
```

**Known limitations / caveats**
- **GT-LEAK:** both outputs draw the ground-truth silhouette/surface. Grader-side / interactive
  only — never embed in a worker prompt or drawing-track spec.
- **ASCII diff is a vertex-cloud projection, not a filled silhouette.** It rasterizes projected
  *vertices*, so coarse meshes give a sparse outline and a single silhouette-edge cell can land
  on a bin boundary and "shimmer" (±1–2 cells of spurious `+`/`·`). The self-test tolerates ≤2
  divergence cells for a part-vs-itself for exactly this reason.
- **`iso` view has no true projection.** `_DROP_AXIS["iso"]` is `None`; for ASCII it falls back
  to the `front` projection (only the PNG path renders a real isometric camera).
- **PNG signed-distance sign is approximate** (nearest-face-normal dot product) and surfaces are
  **decimated above 20k faces** for speed; treat the red/blue coloring as a qualitative
  "protruding vs recessed" cue, not a calibrated distance field. The overlay clips contrast at
  ±5% of the GT diagonal.
- Default mode when you pass neither `--ascii`/`--png`/`--both` is **ASCII**.

---

## `surface_histogram.py` — kernel-stable surface-type topology

**Purpose:** a topology comparison that survives kernel/round-trip differences. Instead of
matching exact B-rep counts (which differ across kernels and STEP round-trips — e.g. 51→49 edges
on the L-bracket), it counts faces **by surface type** (Plane, Cylinder, Cone, Sphere, Torus,
BSpline, Other) and compares candidate vs GT by **cosine similarity**. A missing hole = a missing
Cylinder face → similarity drops. **Importable-only — no CLI.**

**Importable API**
```python
from surface_histogram import surface_histogram, histogram_similarity, from_step, from_candidate

surface_histogram(solid) -> dict            # accepts a Solid/Part/Compound OR a BuildPart
histogram_similarity(hc: dict, hg: dict) -> float   # cosine similarity in [0, 1]
from_step(path) -> object                   # import_step(path) -> solid
from_candidate(py_path, timeout=120) -> object | None   # build candidate -> STEP -> reimport
```
`surface_histogram` accepts a build123d `Solid`/`Part`/`Compound`, any object with a
`.wrapped` `TopoDS_Shape`, **or a `BuildPart` builder** (it resolves `.part` first — the
candidate contract's `result = p` where `p` is a `BuildPart`). Histogram keys are always the 7
canonical types (value may be 0); non-canonical OCC types collapse into `Other`.

**Example**
```python
from surface_histogram import from_candidate, from_step, surface_histogram, histogram_similarity
hc = surface_histogram(from_candidate("candidate.py"))   # e.g. {'Plane': 6, 'Cylinder': 4, ...}
hg = surface_histogram(from_step("some_ref.step"))
sim = histogram_similarity(hc, hg)   # 1.0 = identical type mix
```

**Known limitations / caveats**
- **This is a PROPOSED reward layer, NOT wired into `reward.py`.** The module docstring spells
  out suggested integration (e.g. `topo_s = 0.5*topology_match + 0.5*histogram_similarity`), but
  it **must be reviewed and integrated by a human before touching `reward.py`**. Don't assume the
  live reward uses it.
- **Type histogram, not geometry.** It is invariant to seam-edge merges (the point), but it is
  also **blind to size, position, and count-preserving shape errors**: two parts with the same
  surface-type mix (e.g. same number of planes + cylinders but wrong dimensions or wrong hole
  positions) score 1.0. It complements, never replaces, the volumetric/IoU layers.
- **`histogram_similarity` against a GT histogram is GT-leaking-adjacent** — the GT face-type mix
  is part of the answer. Computing a histogram on a *candidate alone* is safe; comparing it to a
  GT histogram is grader-side only.
- `from_candidate` returns `None` (not an exception) when the candidate fails to build or export
  STEP — check for `None` before calling `surface_histogram`.
- An all-zero histogram (empty solid) makes `histogram_similarity` return `0.0` by definition.

---

## `drawing_extract.py` — engineering-drawing reader → JSON schema

**Purpose:** read a 2D engineering drawing (PNG/JPG/PDF) into a fixed JSON schema via a 6-step
chain-of-thought prompt, then pass it through `normalize_to_mm`. The durable value is the
**schema + the CoT prompt + the unit-normalization integration** — *not* a promise of accuracy
(measured zero-shot: Gemini 2.5 Flash ~77%, Claude Opus ~40%, GD&T ~50%). The vision backend is
pluggable.

**CLI**
```
python drawing_extract.py --drawing <png/jpg/pdf> [--backend auto|gemini|claude|scaffold]
                          [--json] [--discover] [--pmi-probe STEP]
```
- `--drawing` — path to the drawing (PNG/JPG/PDF). Required unless `--discover`/`--pmi-probe`.
- `--backend` — `auto` (gemini if reachable → claude CLI → scaffold), `gemini`, `claude`, or
  `scaffold` (offline; returns the empty schema, never calls a VLM). Default `auto`.
- `--json` — print the full result as JSON (otherwise a short summary).
- `--discover` — report which backends are reachable (no secrets leaked) and exit.
- `--pmi-probe STEP` — run the AP242 native-PMI probe on a STEP file and exit.

**Importable API**
```python
from drawing_extract import (
    extract_drawing, EXTRACTION_PROMPT, EMPTY_SCHEMA,
    probe_ap242_pmi, discover_backends,
)
extract_drawing(png_path, backend="auto") -> dict   # always schema-shaped, always mm-normalized
probe_ap242_pmi(step_path) -> dict                   # native-PMI capability probe
discover_backends() -> dict                          # backend reachability report
```
The result **always** conforms to `EMPTY_SCHEMA`'s shape (`units, unit_source, scale,
views_present, dimensions, features, gdt_frames, title_block`, plus `_backend`/`_warnings`
provenance) and is **always** passed through `normalize_to_mm` before return.

**Example**
```bash
.venv/Scripts/python.exe drawing_extract.py --discover         # which backends are live?
.venv/Scripts/python.exe drawing_extract.py --drawing tasks/trial_lbracket/drawing.png --json
```

**Known limitations / caveats**
- **Accuracy is low and this is by design a scaffold.** Don't treat the extracted dimensions as
  trustworthy — GD&T especially (~50%). Validate against `probe_ap242_pmi` when the STEP carries
  semantic PMI, or against the drawing by eye.
- **Gemini key resolution:** `$GEMINI_API_KEY` → `$GOOGLE_API_KEY` → `$GOOGLE_GENAI_API_KEY` →
  `~/.banana/api_key`. Model order is `gemini-2.5-flash` → `2.0-flash` → `1.5-flash` → `1.5-pro`.
  Uses stdlib `urllib` (the `requests` package is **not installed**). With no key and no reachable
  `claude` CLI, `auto` returns the **scaffold** (empty schema + a `_warnings` note) — not an error.
- **Truncation is possible.** gemini-2.5-\* spends output budget on internal "thinking"; long
  extractions can hit `MAX_TOKENS`. The reader recovers the valid JSON prefix and appends a
  `_warnings` note, so some dimensions/features **near the end may be missing**.
- **`probe_ap242_pmi` is an oracle, not a grader.** It counts semantic PMI labels (and reads the
  first dimension value if present) to *validate* a VLM extraction — it does **not** read geometry
  into a candidate. Do not point it at a hidden answer key you are meant to reconstruct from a
  drawing.
- This is the **safe** member of the GT-leak table only because the drawing is a *given input*,
  not the GT geometry. (The `--pmi-probe` on a hidden GT STEP would leak — don't.)

---

## See also

- [ARCHITECTURE.md](ARCHITECTURE.md) — the harness layer mechanics (reward, runner, geometry, render, feedback) these tools sit beside.
- [known-limitations.md](known-limitations.md) — the *why* behind the scores and the reward/geometry landmines (the topology ceiling, the IoU/chamfer floor, the hole-count blind spot).
