# Lane 2 — `occ_guard.py` (loud-fail guardrails for build123d modeling)

**You are building one file: `occ_guard.py` at the repo root.** Pure addition, importable helper a modeler
uses while building. Do NOT edit `harness/`. Repo: `C:\Users\joshw\CAD Autoresearch\cad-autoresearch`;
`.venv\Scripts\python.exe` (Python 3.13).

## Goal
OpenCASCADE booleans SILENTLY return empty/fragment solids (IsDone()=True on garbage). build123d's
`_bool_op` does `op.Build() → op.Shape()` with ZERO checking between. This module wraps booleans + key ops
so they FAIL LOUD with an actionable message. Catches the 6 failure modes that dominate AI-generated code:
sphere/cone pole degeneracy, non-manifold operand, sequential-cut tolerance collapse, self-intersecting
revolve profile, seam-edge fillet, tangent-only contact.

## VERIFIED ENV FACTS (do not re-derive; build to these)
- `HasErrors()` / `HasWarnings()` are **NOT exposed** on `BRepAlgoAPI_Cut` in this OCP build (tested:
  `hasattr(op,'HasErrors')` → False). **Use the volume + solid-count proxy**, not HasErrors.
- `Shape.volume`, `.is_valid`, `.solids()`, `.fix()`, `.clean()` ALL exist on build123d shapes.
- `Shape.cut()/.fuse()` do **NOT** accept a `tol=` kwarg in this build123d version (tested). Do NOT call
  `base.cut(*tools, tol=...)` — it will error. Either call `base.cut(*tools)` plain, OR for fuzzy value use
  raw OCP (`BRepAlgoAPI_Cut` + `op.SetFuzzyValue(1e-6)` — SetFuzzyValue IS exposed). v1: plain `.cut()` is fine.
- **shapely is NOT installed.** Do NOT use `shapely.geometry.Polygon` for profile self-intersection. For the
  revolve-axis-crossing check use a pure-numpy check (below). Full 2D self-intersection: a small numpy
  segment-pairwise-intersection helper, or skip in v1 (axis-crossing is the high-value killer).

## Build these functions
```python
def safe_cut(base, *tools, label="cut", pre_vol=None): ...   # base.cut(*tools), then _gate
def safe_fuse(base, *tools, label="fuse", pre_vol=None): ...  # base.fuse(*tools), then _gate
def safe_intersect(base, *tools, label="intersect"): ...      # _gate with pre_vol=0 allowed small
def _gate_result(result, pre_vol, label):
    n = len(result.solids()); vol = result.volume
    if n == 0 or vol <= 1e-9: raise ValueError(f"[{label}] empty/zero-volume result — likely "
        "tangent-only contact, sphere/cone pole degeneracy, or non-overlapping geometry.")
    if pre_vol is not None and vol < 0.5*pre_vol: raise ValueError(f"[{label}] volume collapsed "
        f"{pre_vol:.4g}->{vol:.4g} — likely sequential-cut tolerance accumulation; batch cuts into one compound.")

def safe_fillet(solid, edges, radius, label="fillet"):
    # raw OCP BRepFilletAPI_MakeFillet; after Build(): if not mkf.IsDone(): raise with NbFaultyContours();
    # then volume>0 gate.  (IsDone IS a real signal for fillets.)

def check_revolve_profile(pts_2d, axis_x=0.0):
    # pts_2d: list[(x,z)]. numpy only. raise if any x < axis_x-1e-9 (profile crosses the revolve axis →
    # self-intersecting solid). Optionally: shoelace area > 0.  (NO shapely.)

def validate_solid(solid, label="final"):
    # n=len(solid.solids()); vol=solid.volume; raise if n==0 or vol<=1e-9.
    # if not solid.is_valid: warnings.warn(... "call .fix()").  (is_valid wraps BRepCheck_Analyzer.)
```
Keep it ~120 LOC, dependency-free beyond build123d + OCP + numpy.

## Self-test (must pass, include in report)
1. A clean cut (e.g. `Box(20,20,20).cut(Cylinder(r=5,h=30))`) through `safe_cut` → returns, no raise.
2. A tangent/empty case that should RAISE: cut a body by a tool that doesn't overlap it (or fuse two
   non-overlapping boxes via the wrong mode) → `safe_*` raises ValueError with the actionable message.
3. `check_revolve_profile([(0,0),(10,0),(10,10),(-2,10)])` → raises (x=-2 crosses axis);
   `check_revolve_profile([(0,0),(10,0),(10,10),(0,10)])` → no raise.
4. `git status` shows only the new `occ_guard.py`.

## Report back
Files created; the 4 self-test results (paste stdout / the raised messages); note that HasErrors is
unexposed so you used the volume proxy, and that shapely-free axis-check was used. Effort ~3-4h.
