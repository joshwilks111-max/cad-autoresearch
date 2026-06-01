# Lane 7 — surface-type-histogram topology (kernel-stable topology layer)

**This lane TOUCHES `harness/` (guarded code) — build the new metric STANDALONE first, do NOT modify
reward.py in this lane.** Build `surface_histogram.py` at repo root. Propose (don't apply) the reward
integration as a separate reviewed step. Repo: `C:\Users\joshw\CAD Autoresearch\cad-autoresearch`;
`.venv\Scripts\python.exe`.

## Goal
The current topology layer matches EXACT B-rep counts {faces,edges,vertices,euler}. Problem: those counts
differ between CAD kernels and even across a STEP export→import round-trip (we measured 51→49 edges on the
L-bracket). So exact-count matching punishes kernel/STYLE, not geometric wrongness. The frontier-recommended
fix: a **surface-type histogram** — count B-rep faces by type (Plane, Cylinder, Cone, Sphere, Torus,
BSpline, ...) and compare candidate vs GT histograms by cosine similarity. Kernel-stable (seam-edge merges
don't change a face's surface TYPE) yet discriminative (a missing hole = a missing Cylinder face).

## VERIFIED ENV FACT
`from OCP.BRepAdaptor import BRepAdaptor_Surface` and `from OCP.GeomAbs import GeomAbs_Plane,
GeomAbs_Cylinder, GeomAbs_Cone` IMPORT OK (tested). So the histogram is feasible.

## Build (`surface_histogram.py`)
```python
def surface_histogram(solid) -> dict:
    """solid: a build123d/OCP solid (has .wrapped). Walk every face, classify by BRepAdaptor_Surface(face).
    GetType() against GeomAbs_* enum, return a count dict {'Plane':N,'Cylinder':M,'Cone':..,'Sphere':..,
    'Torus':..,'BSplineSurface':..,'Other':..}."""
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                             GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BSplineSurface)
    # iterate faces (TopExp_Explorer on solid.wrapped, TopAbs_FACE), TopoDS.Face_s(exp.Current()),
    # BRepAdaptor_Surface(face).GetType() -> map enum to a name -> Counter.

def histogram_similarity(hc: dict, hg: dict) -> float:
    """Cosine similarity of the two count vectors over the union of keys, in [0,1]."""
```
Also provide a `from_step(path)` helper (`build123d.import_step`) and a `from_candidate(py_path)` helper
(reuse `harness.run_candidate`, then it returns a mesh not a solid — so for a `.py` you need the solid:
simplest is to `import_step` the RunResult.step_path). Keep ~60-80 LOC.

## Self-test (must pass, include in report)
1. `surface_histogram(import_step('tasks/bearing_608/ground_truth/result.step'))` → an annulus = 2 Plane
   (top+bottom rings) + 2 Cylinder (OD + bore) = {Plane:2, Cylinder:2} (or similar). Paste it.
2. `surface_histogram(import_step('tasks/trial_lbracket/ground_truth/result.step'))` → mostly Planes + some
   Cylinders (the 6 bolt holes) + the gusset. Paste it.
3. `histogram_similarity(h, h)` == 1.0; similarity of the bearing vs the L-bracket < 1.0. Paste both.
4. CRUCIAL kernel-stability check: histogram of the GT solid built in-memory vs histogram of the SAME part
   after STEP export→re-import — should be IDENTICAL (unlike exact edge counts which shifted 51→49). Paste
   both to prove kernel-stability. (Build the L-bracket in-memory via tasks/trial_lbracket/make_ground_truth
   build(), and import_step its result.step; compare histograms.)
5. `git status` shows only the new `surface_histogram.py` (NO reward.py edit).

## Report back
File created; all self-test outputs (paste); the kernel-stability result (this is the whole point — does the
histogram survive the round-trip that broke exact counts?); and a SHORT proposed integration note: how this
would slot into reward.py (replace or supplement `topology_match`; suggested weight) — as a PROPOSAL for a
later reviewed harness change, NOT applied now. Effort ~2-4h.
