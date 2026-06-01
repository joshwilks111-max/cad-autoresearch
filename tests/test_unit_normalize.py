"""
test_unit_normalize.py — lock the unit-detection + inch->mm normalisation.

Pure Python, no mesh/kernel — runs in milliseconds. Locks the two silent-corruption
bugs found in the /review pass:
  1. case-sensitive inch match ('IN'/'inches' escaped conversion -> 25.4x miss)
  2. over-broad 'tol' substring match (scaled 'tolerance_class' categorical x25.4)

Run from repo root:   pytest -q tests/test_unit_normalize.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from unit_normalize import detect_units, normalize_to_mm, _is_numeric_dim_field  # noqa: E402


# ── detect_units ───────────────────────────────────────────────────────────
def test_tolerance_note_detects_inches():
    assert detect_units(title_block_text="UNLESS OTHERWISE SPECIFIED +/-0.005 IN")[0] == "in"


def test_keyword_mm():
    assert detect_units(title_block_text="ALL DIMS MM")[0] == "mm"


def test_magnitude_inference_inches():
    assert detect_units(dimension_values=[0.5, 1.25, 2.0, 3.5]) == ("in", "magnitude_inference")


def test_magnitude_boundaries():
    # < 12 -> in ; > 15 -> mm ; 12..15 inclusive -> ambiguous (the real band, not 6-15)
    assert detect_units(dimension_values=[11.9])[0] == "in"
    assert detect_units(dimension_values=[12.0])[0] == "unknown"
    assert detect_units(dimension_values=[15.0])[0] == "unknown"
    assert detect_units(dimension_values=[20.0])[0] == "mm"


# ── normalize_to_mm: case-insensitivity (review bug #1) ─────────────────────
def test_inch_aliases_all_convert():
    """'in','IN','In','inch','inches','INCH','"' all mean inches and MUST x25.4.
    A bare units != 'in' check let the uppercase/word forms escape silently."""
    for u in ("in", "IN", "In", "inch", "inches", "INCH", '"'):
        d = normalize_to_mm({"units": u, "dimensions": [{"nominal_mm": 1.0}]})
        assert abs(d["dimensions"][0]["nominal_mm"] - 25.4) < 1e-9, f"units={u!r} did not convert"
        assert d["units"] == "mm" and d["conversion_applied"] is True


def test_mm_and_unknown_unchanged():
    for u in ("mm", "MM", "unknown", "millimeter"):
        d = normalize_to_mm({"units": u, "dimensions": [{"nominal_mm": 3.0}]})
        assert d["dimensions"][0]["nominal_mm"] == 3.0
        assert d.get("conversion_applied") is False


# ── normalize_to_mm: scaling + idempotency ─────────────────────────────────
def test_scales_dims_tols_and_is_idempotent():
    d = {"units": "in",
         "dimensions": [{"nominal_mm": 1.0, "upper_tol_mm": 0.01, "lower_tol_mm": -0.01}],
         "features": [{"diameter": 0.5, "depth": 0.25}]}
    out = normalize_to_mm(d)
    assert abs(out["dimensions"][0]["nominal_mm"] - 25.4) < 1e-9
    assert abs(out["dimensions"][0]["upper_tol_mm"] - 0.254) < 1e-9
    assert abs(out["features"][0]["diameter"] - 12.7) < 1e-9
    # idempotent: a second pass must NOT double-convert
    again = normalize_to_mm(out)
    assert abs(again["dimensions"][0]["nominal_mm"] - 25.4) < 1e-9


# ── field matcher: the 'tol' over-match bug (review bug #4) ─────────────────
def test_field_matcher_includes_linear_fields():
    for k in ("nominal_mm", "upper_tol_mm", "lower_tol_mm", "tolerance_mm",
              "tolerance", "diameter", "radius", "depth", "upper_tol"):
        assert _is_numeric_dim_field(k) is True, f"{k} should be convertible"


def test_field_matcher_excludes_categoricals_and_angles():
    # categoricals / counts that share a prefix with real fields must NOT scale
    for k in ("tolerance_class", "tolerance_grade", "total_holes", "hole_count",
              "quantity", "angle_tol", "taper_deg"):
        assert _is_numeric_dim_field(k) is False, f"{k} must NOT be scaled"


def test_categorical_not_scaled_end_to_end():
    """An inch part carrying a GD&T 'tolerance_class' and a 'total_holes' count:
    the lengths convert, the categoricals/counts stay put."""
    d = {"units": "in", "tolerance_class": 2, "total_holes": 4,
         "dimensions": [{"nominal_mm": 1.0}]}
    out = normalize_to_mm(d)
    assert out["tolerance_class"] == 2          # NOT 50.8
    assert out["total_holes"] == 4              # NOT 101.6
    assert abs(out["dimensions"][0]["nominal_mm"] - 25.4) < 1e-9
