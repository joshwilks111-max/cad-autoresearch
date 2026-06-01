"""
surface_histogram.py — kernel-stable topology layer: surface-type histogram.

The existing topology layer matches EXACT B-rep counts {faces, edges, vertices,
euler}. Problem: those counts differ between CAD kernels and even across a STEP
export -> import round-trip (51->49 edges on the L-bracket). So exact-count
matching punishes kernel/style, not geometric wrongness.

Fix: a surface-TYPE histogram — count B-rep faces by type (Plane, Cylinder,
Cone, Sphere, Torus, BSpline, Other) and compare candidate vs GT histograms by
cosine similarity. A face's surface TYPE is invariant to seam-edge merges that
accompany STEP round-trips: merging two seam edges into one doesn't change the
face type of either neighbouring face. Yet the histogram remains discriminative:
a missing hole = a missing Cylinder face -> cosine similarity drops.

PROPOSED (not applied) reward integration note:
  - Replace or supplement `topology_match` in reward.py Layer 4.
  - Suggested weight: keep w_topology=0.15 but compute it as:
      topo_s = 0.5 * topology_match(sig_c, sig_g) + 0.5 * histogram_similarity(hc, hg)
  - Or swap entirely: topo_s = histogram_similarity(hc, hg) (drops kernel false
    negatives at the cost of losing per-face-count discrimination for totally
    wrong topologies). Hybrid is safer — exact counts still matter for simple parts.
  - This module must be reviewed and integrated by a human before touching reward.py.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path


# ── surface-type name map  ───────────────────────────────────────────────────
# GeomAbs enum integer values are stable across OCC versions.
_TYPE_NAMES = {
    0: "Plane",
    1: "Cylinder",
    2: "Cone",
    3: "Sphere",
    4: "Torus",
    5: "BezierSurface",
    6: "BSplineSurface",
    7: "SurfaceOfRevolution",
    8: "SurfaceOfExtrusion",
    9: "OffsetSurface",
    10: "OtherSurface",
}
_CANONICAL_KEYS = ["Plane", "Cylinder", "Cone", "Sphere", "Torus",
                   "BSplineSurface", "Other"]


def surface_histogram(solid) -> dict:
    """Walk every B-rep face of *solid* and classify by surface type.

    Parameters
    ----------
    solid : build123d Solid/Part/Compound or any object with a ``.wrapped``
            attribute that is a TopoDS_Shape.

    Returns
    -------
    dict  — keys are type names from _CANONICAL_KEYS (always present, value may
            be 0).  Any OCC type not in the canonical list falls into "Other".
    """
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    hist: dict[str, int] = {k: 0 for k in _CANONICAL_KEYS}

    # Accept a raw OCC shape or a build123d wrapper.
    shape = getattr(solid, "wrapped", solid)

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        surf_type_int = int(BRepAdaptor_Surface(face).GetType())
        name = _TYPE_NAMES.get(surf_type_int, "Other")
        # Collapse all non-canonical types into "Other"
        if name not in hist:
            name = "Other"
        hist[name] += 1
        exp.Next()

    return hist


def histogram_similarity(hc: dict, hg: dict) -> float:
    """Cosine similarity of two surface-type count vectors, in [0, 1].

    Uses the UNION of keys from both histograms so missing types (count 0 in
    one, positive in the other) are penalised.  Returns 1.0 when both are
    identical, 0.0 when orthogonal (no shared surface types at all).
    """
    keys = set(hc) | set(hg)
    vc = [hc.get(k, 0) for k in keys]
    vg = [hg.get(k, 0) for k in keys]

    dot = sum(a * b for a, b in zip(vc, vg))
    norm_c = math.sqrt(sum(a * a for a in vc))
    norm_g = math.sqrt(sum(b * b for b in vg))

    if norm_c < 1e-12 or norm_g < 1e-12:
        # Edge case: one or both histograms are all-zero (empty solid).
        return 0.0

    return float(dot / (norm_c * norm_g))


# ── helpers ──────────────────────────────────────────────────────────────────

def from_step(path: str | Path) -> object:
    """Import a STEP file and return a build123d solid/compound."""
    from build123d import import_step
    return import_step(str(path))


def from_candidate(py_path: str | Path, timeout: int = 120) -> object | None:
    """Run a candidate .py file in the harness sandbox, export to STEP, and
    re-import it as a solid for histogram analysis.

    Returns the solid or None on failure.  Uses a unique temp workspace so it
    never races with runs/manual/ or any parallel worker.
    """
    from harness.runner import run_candidate
    from build123d import import_step

    py_path = Path(py_path)
    code = py_path.read_text(encoding="utf-8")

    ws = tempfile.mkdtemp(prefix=f"_lane7_{py_path.stem}_")
    result = run_candidate(code, workspace=ws, timeout=timeout)

    if not result.ok or result.step_path is None:
        return None
    return import_step(str(result.step_path))
