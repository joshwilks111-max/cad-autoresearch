# PROPOSAL (NOT APPLIED) — wire surface-histogram topology into reward.py

**Status:** draft for review. Touches GUARDED code (`harness/reward.py`, `harness/runner.py`).
Do NOT apply without explicit approval. This document is the whole change, ready to paste,
plus the regression plan that must pass first.

**Author's recommendation:** ship the `surface_histogram` half (Change A+B below). Hold the
`hole_metrics` half — dogfooding found it misses holes in a thin feature of a tall part
(section planes at bbox fractions never slice an 8 mm base in a 44 mm-tall part), so it is
not yet reliable enough to feed a score. See `gbrain: toolbuild-dogfood-findings-2026-06-01`.

---

## Why (the measured case for the histogram)

The current Layer-4 topology (`reward.py:191`, `topo_s = G.topology_match(sig_c, sig_g)`)
matches EXACT B-rep counts {faces, edges, vertices, euler}. Two measured problems:

1. **Kernel/style fragility.** A byte-identical STEP export→import shifts the L-bracket
   51→49 edges, 34→32 vertices. Exact-count matching then punishes a *perfect* submission.
   (This is why `tasks/trial_lbracket/make_ground_truth.py` had to sign its topology.json
   from the RE-imported STEP — a workaround the histogram makes unnecessary.)
2. **Verified discriminative power retained.** The surface-TYPE histogram is invariant to
   seam-edge merges (merging two seam edges doesn't change either neighbour face's TYPE)
   yet still catches a missing hole (a missing Cylinder face). Independently verified:
   `surface_histogram` of the L-bracket in-memory `{Plane:13, Cylinder:4}` == the re-imported
   STEP `{Plane:13, Cylinder:4}` — IDENTICAL across the exact round-trip that broke edge
   counts. And on CTC-05's candidate it reads `{Plane:27, Cylinder:29, Cone:3}` = 59 faces
   vs GT's 156 — a real, typed topology-gap signal.

**Net:** a hybrid Layer 4 keeps exact-count discrimination for simple parts AND stops
penalising kernel/style on complex ones.

---

## The architectural constraint (do not skip)

`score()` already takes `candidate_sig`/`gt_sig` as PRECOMPUTED DICTS (`reward.py:143-144`)
because "OpenCASCADE objects cannot be pickled back to the parent process" — the runner
computes the B-rep signature INSIDE the sandbox subprocess (`runner.py:108-126`) and writes
`topology.json`. **A surface histogram MUST follow the identical pattern:** compute it in the
sandbox epilogue, serialise to `histogram.json`, read it in the parent, pass it into `score()`.
You CANNOT compute it in `score()` from a `*_solid` arg in the normal grading path — there is
no live solid there. (The `*_solid` args work only for in-process callers like a unit test.)

---

## Change A — `harness/runner.py` sandbox epilogue: also emit `histogram.json`

In `__ar_export()` (the epilogue appended to every candidate), right after the `topology.json`
block (currently `runner.py:107-126`), add a surface-type histogram walk. VERIFIED: the existing
topology block binds `w = getattr(solid, "wrapped", solid)` (runner.py:112) — the resolved
`TopoDS_Shape`. Reuse that exact `w` (it is in scope at the end of the block; or re-bind it
identically). Add immediately after line 126:

```python
        # --- surface-type histogram (kernel-stable topology, parallel to sig) ---
        hist = None
        try:
            from OCP.TopExp import TopExp_Explorer as _TE
            from OCP.TopAbs import TopAbs_FACE as _FACE
            from OCP.TopoDS import TopoDS as _TDS
            from OCP.BRepAdaptor import BRepAdaptor_Surface as _BAS
            _NAMES = {0:"Plane",1:"Cylinder",2:"Cone",3:"Sphere",4:"Torus",6:"BSplineSurface"}
            _KEYS = ["Plane","Cylinder","Cone","Sphere","Torus","BSplineSurface","Other"]
            hist = {k: 0 for k in _KEYS}
            _wh = getattr(solid, "wrapped", solid)        # SAME shape the topo walk used (== w)
            _exp = _TE(_wh, _FACE)
            while _exp.More():
                _t = int(_BAS(_TDS.Face_s(_exp.Current())).GetType())
                _nm = _NAMES.get(_t, "Other")
                hist[_nm if _nm in hist else "Other"] += 1
                _exp.Next()
        except Exception:
            hist = None
        with open(_os.path.join(out, "histogram.json"), "w") as f:
            _json.dump(hist, f)
```

NOTE: this re-binds `_wh = getattr(solid, "wrapped", solid)` to match the topo block's `w`
(runner.py:112) rather than assume `w` is still in scope — self-contained, zero coupling risk.
Do NOT re-resolve `result`; `solid` is the already-resolved object from the export step above.

Then extend `RunResult` + its construction (`runner.py:~198`) to carry it:

```python
        histogram=_read_json(ws / "histogram.json"),   # add beside topology=...
```
and add `histogram: dict | None = None` to the `RunResult` dataclass.

## Change B — `harness/reward.py`: hybrid Layer 4

Add a tolerant import at module top (the tool lives at repo root, already on sys.path for
in-repo callers):

```python
try:
    from surface_histogram import histogram_similarity as _hist_sim
except Exception:
    _hist_sim = None
```

Extend `score()`'s signature with two optional dicts (mirroring `*_sig`):

```python
def score(candidate_mesh, gt_mesh, candidate_solid=None, gt_solid=None,
          candidate_sig=None, gt_sig=None,
          candidate_hist=None, gt_hist=None,          # <-- NEW
          cfg=None):
```

Replace the single Layer-4 line (`reward.py:191`) with the hybrid:

```python
    exact_topo = G.topology_match(sig_c, sig_g)
    if _hist_sim is not None and candidate_hist and gt_hist:
        hist_s = _hist_sim(candidate_hist, gt_hist)
        topo_s = cfg.topo_exact_w * exact_topo + (1.0 - cfg.topo_exact_w) * hist_s
        raw["topology_exact"], raw["topology_hist"] = exact_topo, hist_s
    else:
        topo_s = exact_topo
    raw["topology_candidate"], raw["topology_gt"] = sig_c, sig_g
```

Add one knob to `RewardConfig` (default 0.5, the lane7-recommended blend):

```python
    topo_exact_w: float = 0.5   # Layer-4 blend: exact-count vs surface-type histogram
```

**Weighting:** keep `w_topology` unchanged (0.15 + adaptive). The layer becomes more
*reliable*, not more important. `_adaptive_weights` is untouched.

## Change C — thread the histogram through the caller (`grade_one.py` / `run_inner_loop.py`)

Wherever `score(...)` is called with `candidate_sig=run.topology`, also pass
`candidate_hist=run.histogram`. The GT side needs a histogram too: compute it ONCE when the
GT is built (add a `histogram.json` write to each `tasks/*/make_ground_truth.py` epilogue, OR
compute it lazily in `load_ground_truth` via `surface_histogram.from_step`). The lazy path in
`load_ground_truth` is less invasive and keeps task scaffolds unchanged:

```python
    # in load_ground_truth, after importing the GT solid/mesh:
    try:
        from surface_histogram import surface_histogram
        gt_hist = surface_histogram(import_step(str(gt_step)))
    except Exception:
        gt_hist = None
```

---

## REGRESSION PLAN — must pass BEFORE this is applied

1. **Zero-regression on solved parts.** Re-grade every committed `best_candidate.py`
   (bearing_608, the 3 round parts, motor_mount, FTC-11, sample_bracket) and assert each
   composite is within ±0.005 of its recorded `.best_score`. The hybrid at w=0.5 must NOT
   move a solved score materially (these are already topo≈1.0, hist≈1.0).
2. **The L-bracket workaround becomes unnecessary.** With the histogram half live, signing
   `trial_lbracket` topology.json from the IN-MEMORY solid (the thing that used to score
   topo 0.714) should now grade a perfect submission ≥0.95 — because the histogram half is
   1.0 regardless of the 51↔49 edge shift. Prove it both ways.
3. **CTC-05 does not inflate.** Its candidate hist {27,29,3} vs GT 156 faces must still leave
   topo well below 1.0 (the histogram is similar-shape but the count vector differs) — assert
   composite stays in the honest 0.66–0.72 band, NOT a spurious jump. (Guards against the
   histogram being too forgiving on a genuinely incomplete part — the failure mode to
   check is two DIFFERENT parts with the SAME face-type counts: e.g. a 20 mm cube vs a
   50 mm cube (both {Plane:6} → histogram_similarity 1.0 despite different geometry), or
   two distinct 6-plane prismatic parts. The histogram cannot tell them apart; the exact-
   count + IoU + bbox layers must. NOTE: a box vs a sphere is NOT this failure — a box is
   {Plane:6}, a sphere is {Sphere:1}, similarity 0.0 (verified). Counts differ, so the
   histogram correctly distinguishes them.)
4. **`tests/test_reward.py` green** + add 2 cases: (a) hybrid == exact when hist args are
   None (back-comp); (b) a known seam-shift pair scores higher under hybrid than under exact.
5. **Determinism:** the histogram walk is RNG-free; assert byte-identical `histogram.json`
   across two runs of the same candidate.

## Risk register
- **Same-histogram-different-geometry false match** (e.g. a 20 mm cube vs a 50 mm cube,
  both {Plane:6}, histogram_similarity 1.0): the HYBRID (0.5 exact + 0.5 hist) contains
  this — exact-count + IoU + bbox still penalise it. A pure-histogram swap would NOT; do
  not swap, blend. (A box vs a sphere is NOT a false match: {Plane:6} vs {Sphere:1},
  similarity 0.0 — verified. The histogram only over-forgives when the face-TYPE COUNTS
  coincide, which is scale/position differences of the same topology, not different shapes.)
- **GT histogram source drift:** if computed lazily via `from_step`, it must use the SAME
  tessellation-irrelevant B-rep walk (it does — histogram is from the solid, not the mesh).
- **Guarded-code blast radius:** Changes A+B+C touch runner.py, reward.py, RewardConfig, and a
  caller. `code_callers`/`code_blast` on `score` + `RunResult` before applying.

## NOT in this proposal
- `hole_metrics` integration — held until its thin-feature section-placement bug is fixed.
- Any weight change — `w_topology` stays 0.15 + adaptive.
