"""
occ_guard.py — loud-fail guardrails for build123d / OCP boolean ops.

Background: BRepAlgoAPI_Cut/Fuse silently return empty or fragment solids
(IsDone()=True on garbage). HasErrors/HasWarnings are NOT exposed in this OCP
build (verified: hasattr(op,'HasErrors') -> False). This module uses the
volume + solid-count proxy to detect failures, and raises ValueError with an
actionable message.

Tested against: build123d on OCP/OCC 7.8, Python 3.13.
shapely is NOT installed; revolve-axis check uses pure numpy.
"""

from __future__ import annotations

import warnings
import numpy as np

from build123d import Box, Cylinder, Sphere  # noqa: F401 (re-exported for tests)
from build123d.topology import Shape, Solid
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.Standard import Standard_Failure


# ---------------------------------------------------------------------------
# Internal gate — shared by safe_cut / safe_fuse / safe_intersect
# ---------------------------------------------------------------------------

def _gate_result(result, pre_vol, label):
    """Raise ValueError if result is empty or volume collapsed unexpectedly.

    Args:
        result:   build123d Shape returned from a boolean op.
        pre_vol:  volume of the base solid BEFORE the op (None to skip the
                  collapse check; 0 to allow small results, e.g. intersect).
        label:    human name for the operation, included in the error message.
    """
    n = len(result.solids())
    vol = result.volume
    if n == 0 or vol <= 1e-9:
        raise ValueError(
            f"[{label}] empty/zero-volume result — likely "
            "tangent-only contact, sphere/cone pole degeneracy, "
            "or non-overlapping geometry."
        )
    if pre_vol is not None and pre_vol > 0 and vol < 0.5 * pre_vol:
        raise ValueError(
            f"[{label}] volume collapsed {pre_vol:.4g}->{vol:.4g} — "
            "likely sequential-cut tolerance accumulation; "
            "batch cuts into one compound."
        )


# ---------------------------------------------------------------------------
# Safe boolean wrappers
# ---------------------------------------------------------------------------

def safe_cut(base, *tools, label="cut", pre_vol=None):
    """Cut base by each tool in sequence; raise loud ValueError on failure.

    Args:
        base:     build123d solid (the stock to cut from).
        *tools:   one or more build123d solids to subtract.
        label:    descriptive name for error messages.
        pre_vol:  if provided, used for volume-collapse detection. If None
                  the base volume is measured automatically.

    Returns:
        The result solid (build123d shape).

    Raises:
        ValueError: if the result is empty, zero-volume, or shows >50% volume
                    collapse compared to pre_vol.
    """
    if pre_vol is None:
        pre_vol = base.volume
    result = base.cut(*tools)
    _gate_result(result, pre_vol, label)
    return result


def safe_fuse(base, *tools, label="fuse", pre_vol=None):
    """Fuse base with each tool; raise loud ValueError on failure.

    Args:
        base:     build123d solid (primary body).
        *tools:   one or more build123d solids to fuse with.
        label:    descriptive name for error messages.
        pre_vol:  baseline volume for collapse detection (auto-measured if None).

    Returns:
        The fused result solid.

    Raises:
        ValueError: if the result is empty or zero-volume.
    """
    if pre_vol is None:
        pre_vol = base.volume
    result = base.fuse(*tools)
    _gate_result(result, pre_vol, label)
    return result


def safe_intersect(base, *tools, label="intersect"):
    """Intersect base with tools; raise loud ValueError if result is empty.

    Intersection results are allowed to have small volume (the collapse
    threshold is not applied). The only gate is non-zero solid count and volume.

    Args:
        base:   build123d solid.
        *tools: one or more build123d solids to intersect with.
        label:  descriptive name for error messages.

    Returns:
        The intersection result.

    Raises:
        ValueError: if the intersection is empty (non-overlapping geometry).
    """
    result = base.intersect(*tools)
    _gate_result(result, pre_vol=0, label=label)
    return result


# ---------------------------------------------------------------------------
# Safe fillet
# ---------------------------------------------------------------------------

def safe_fillet(solid, edges, radius, label="fillet"):
    """Apply a fillet via raw OCP BRepFilletAPI_MakeFillet with loud failure.

    build123d's .fillet() can silently produce bad geometry or raise
    uncommunicative exceptions. This wrapper:
      - Uses BRepFilletAPI_MakeFillet directly so we control error checking.
      - After Build(): checks IsDone() — a real signal for fillets (unlike
        BRepAlgoAPI_Cut where HasErrors is not exposed).
      - Also gates on volume > 0 in case IsDone lies.

    Args:
        solid:  build123d solid to fillet.
        edges:  iterable of build123d Edge objects to fillet.
        radius: fillet radius (mm or model units).
        label:  descriptive name for error messages.

    Returns:
        A new build123d Solid with the fillet applied.

    Raises:
        ValueError: if fillet fails (IsDone=False) or result is empty.
    """
    mkf = BRepFilletAPI_MakeFillet(solid.wrapped)
    for e in edges:
        mkf.Add(radius, e.wrapped)
    try:
        mkf.Build()
    except Standard_Failure as ex:
        raise ValueError(
            f"[{label}] fillet Build() raised OCC Standard_Failure: {ex} — "
            "likely a seam edge, non-manifold edge, or tangent-only contact."
        ) from ex

    if not mkf.IsDone():
        n_faulty = mkf.NbFaultyContours()
        raise ValueError(
            f"[{label}] fillet failed (IsDone=False, NbFaultyContours={n_faulty}) — "
            "likely seam-edge fillet, tangent-only contact, or radius too large "
            "for the geometry."
        )

    result = Solid(mkf.Shape())
    if result.volume <= 1e-9:
        raise ValueError(
            f"[{label}] fillet returned zero-volume solid — "
            "OCC reported success but the geometry is degenerate."
        )
    return result


# ---------------------------------------------------------------------------
# Revolve-profile axis-crossing check (no shapely — pure numpy)
# ---------------------------------------------------------------------------

def check_revolve_profile(pts_2d, axis_x=0.0):
    """Raise if a 2D revolve profile crosses the rotation axis.

    Crossing the revolve axis produces a self-intersecting solid. This check
    uses a pure-numpy approach: if any vertex has x < axis_x - 1e-9 the
    profile is already invalid. For a more thorough check the segment
    intersection test below catches cases where only edges (not vertices)
    cross.

    Args:
        pts_2d:  list of (x, z) tuples defining the profile polygon. The
                 polygon is assumed closed (last point connects to first).
        axis_x:  x-coordinate of the revolve axis (default 0.0).

    Raises:
        ValueError: if any vertex or profile segment crosses x < axis_x.
    """
    pts = np.asarray(pts_2d, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(
            "check_revolve_profile: pts_2d must be a list of (x, z) pairs."
        )

    # 1. Fast vertex check
    x_vals = pts[:, 0]
    if np.any(x_vals < axis_x - 1e-9):
        bad = np.where(x_vals < axis_x - 1e-9)[0]
        raise ValueError(
            f"revolve profile crosses the rotation axis (x={axis_x}): "
            f"vertices at indices {bad.tolist()} have x={x_vals[bad].tolist()} — "
            "this would produce a self-intersecting solid."
        )

    # 2. Edge-crossing check: does any segment cross from x>=axis_x to x<axis_x?
    #    Use linear interpolation to find where each edge crosses axis_x.
    n = len(pts)
    for i in range(n):
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        x1, x2 = p1[0], p2[0]
        # Check if segment spans across axis_x (one side left, one right)
        # Both above passes vertex check; only need to catch if lerp crosses
        # (already caught by vertex check — but be explicit for clarity)
        if (x1 - axis_x) * (x2 - axis_x) < -1e-18:
            # Segment crosses axis_x — find crossing z
            t = (axis_x - x1) / (x2 - x1)
            z_cross = p1[1] + t * (p2[1] - p1[1])
            raise ValueError(
                f"revolve profile edge [{i}->{(i+1)%n}] crosses the rotation "
                f"axis at x={axis_x}, z≈{z_cross:.4g} — "
                "this would produce a self-intersecting solid."
            )


# ---------------------------------------------------------------------------
# Final solid validator
# ---------------------------------------------------------------------------

def validate_solid(solid, label="final"):
    """Assert that a solid is non-empty and warn if it is not valid per BRep.

    Args:
        solid:  build123d solid to validate.
        label:  descriptive name for error messages.

    Raises:
        ValueError: if solid has zero solids or zero/negative volume.

    Warns:
        UserWarning: if solid.is_valid is False (wraps BRepCheck_Analyzer).
                     The geometry is not necessarily unusable, but callers
                     should consider calling .fix() before export.
    """
    n = len(solid.solids())
    vol = solid.volume
    if n == 0 or vol <= 1e-9:
        raise ValueError(
            f"[{label}] solid is empty or zero-volume "
            f"(solids={n}, volume={vol:.4g})."
        )
    if not solid.is_valid:
        warnings.warn(
            f"[{label}] solid.is_valid=False (BRepCheck_Analyzer flagged issues) — "
            "consider calling .fix() before export.",
            UserWarning,
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# Self-test  (python occ_guard.py [--selftest])
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Exercise every guard on clean + degenerate geometry. Returns exit code."""
    n_pass = n_fail = 0

    def check(name, fn, expect_raise):
        nonlocal n_pass, n_fail
        try:
            fn()
            raised = None
        except Exception as e:  # noqa: BLE001 - we want to see exactly what raised
            raised = e
        ok = (raised is not None) if expect_raise else (raised is None)
        if ok:
            n_pass += 1
            tail = f" (raised: {raised})" if expect_raise and raised else ""
            print(f"  [PASS] {name}{tail}")
        else:
            n_fail += 1
            print(f"  [FAIL] {name}  expected {'raise' if expect_raise else 'no-raise'}, "
                  f"got {raised!r}")

    print("=" * 60)
    print("occ_guard.py self-test")
    print("=" * 60)

    # 1. clean safe_cut: a box with a through-bore — must succeed
    check("safe_cut clean (box - cylinder)",
          lambda: safe_cut(Box(20, 20, 20), Cylinder(radius=5, height=30)),
          expect_raise=False)

    # 2. non-overlapping intersect -> empty -> raise
    check("non-overlap intersect raises",
          lambda: safe_intersect(Box(10, 10, 10),
                                 Box(10, 10, 10).translate((100, 0, 0))),
          expect_raise=True)

    # 2b. non-overlapping cut leaves base intact -> must NOT raise
    check("non-overlap cut no-raise (base unchanged)",
          lambda: safe_cut(Box(20, 20, 20),
                           Box(5, 5, 5).translate((100, 0, 0))),
          expect_raise=False)

    # 3a. revolve profile crossing the axis (x<0) -> raise
    check("revolve axis-crossing raises",
          lambda: check_revolve_profile([(0, 0), (10, 0), (10, 10), (-2, 10)]),
          expect_raise=True)

    # 3b. valid revolve profile (all x>=0) -> no raise
    check("revolve valid profile no-raise",
          lambda: check_revolve_profile([(0, 0), (10, 0), (10, 10), (0, 10)]),
          expect_raise=False)

    # 4. validate_solid on a clean box -> no raise
    check("validate_solid clean box",
          lambda: validate_solid(Box(20, 20, 20)),
          expect_raise=False)

    # 5. safe_fillet with a sane radius on a box edge -> no raise
    def _fillet_good():
        b = Box(20, 20, 20)
        safe_fillet(b, b.edges(), 1.0)
    check("safe_fillet sane radius no-raise", _fillet_good, expect_raise=False)

    # 6. safe_fillet with an absurd radius (> half the box) -> raise
    def _fillet_bad():
        b = Box(20, 20, 20)
        safe_fillet(b, b.edges(), 50.0)
    check("safe_fillet absurd radius raises", _fillet_bad, expect_raise=True)

    print("=" * 60)
    print(f"Results: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 60)
    if n_fail:
        print("SELF-TEST FAILED")
        return 1
    print("ALL OCC_GUARD SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_selftest())
