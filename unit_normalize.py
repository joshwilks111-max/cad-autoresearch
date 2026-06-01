"""unit_normalize.py — deterministic unit detection and mm normalisation.

Architectural fix: route ALL dimension values through normalize_to_mm()
before any value reaches build123d. This makes the inch-vs-mm bug impossible.
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

_MM_KEYWORDS = re.compile(
    r"\bMILLIMET|\bMM\b|±\s*[\d.]+\s*MM",
    re.IGNORECASE,
)

_IN_KEYWORDS = re.compile(
    r"\bINCH|\bINS\b|±\s*[\d.]+\s*IN\b|\bIN\b(?!\s*\w)|\"",
    re.IGNORECASE,
)

# Tolerance note patterns — e.g. "±0.005 IN" or "±0.13 MM"
_TOL_IN = re.compile(r"[±+\-]\s*[\d.]+\s*IN\b", re.IGNORECASE)
_TOL_MM = re.compile(r"[±+\-]\s*[\d.]+\s*MM\b", re.IGNORECASE)

# Dimension scale thresholds (Tier 2)
_SMALL_THRESHOLD = 12.0   # median < 12 → likely inches (machined part)
_LARGE_THRESHOLD = 15.0   # median > 15 → likely mm


def _median(values: list[float]) -> float:
    try:
        import numpy as np  # noqa: PLC0415
        return float(np.median(values))
    except ImportError:
        sorted_v = sorted(values)
        n = len(sorted_v)
        mid = n // 2
        if n % 2 == 1:
            return sorted_v[mid]
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def detect_units(
    *,
    title_block_text: str = "",
    explicit: str | None = None,
    dimension_values: list[float] | None = None,
    part_category: str | None = None,
) -> tuple[str, str]:
    """Return (units, source) where units in {'mm', 'in', 'unknown'}.

    Three-tier heuristic:

    Tier 1 (strongest) — keyword / tolerance-note scan of title_block_text,
      or the ``explicit`` override:
        'MILLIMET' / 'MM' keyword  → ('mm', 'title_block')
        'INCH' / '"' / ' IN '      → ('in', 'title_block')
        '±0.005 IN' tolerance note → ('in', 'tolerance_note')
        '±0.13 MM' tolerance note  → ('mm', 'tolerance_note')
        explicit='mm'|'in'         → that units, source='explicit'

    Tier 2 (magnitude sanity, Tier 1 silent):
        median(|dim_values|) < 12  → ('in',  'magnitude_inference')
        median(|dim_values|) > 15  → ('mm',  'magnitude_inference')
        6–15                       → ('unknown', 'magnitude_ambiguous')

    Tier 3 (part_category prior, last resort):
        'us'/'aerospace'/'asme'    → ('in', 'category_prior')
        'iso'/'european'           → ('mm', 'category_prior')

    Returns ('unknown', 'none') if nothing fires.
    """

    # ------------------------------------------------------------------ #
    # Tier 1a — explicit override
    # ------------------------------------------------------------------ #
    if explicit is not None:
        unit = explicit.strip().lower()
        if unit in ("mm", "millimeter", "millimeters", "metric"):
            return ("mm", "explicit")
        if unit in ("in", "inch", "inches", "imperial"):
            return ("in", "explicit")

    # ------------------------------------------------------------------ #
    # Tier 1b — tolerance note scan (checked BEFORE generic keyword scan
    # because it is more specific and the spec lists it as a separate source)
    # ------------------------------------------------------------------ #
    text = title_block_text.upper()

    if _TOL_IN.search(title_block_text):
        return ("in", "tolerance_note")
    if _TOL_MM.search(title_block_text):
        return ("mm", "tolerance_note")

    # ------------------------------------------------------------------ #
    # Tier 1c — generic keyword scan
    # ------------------------------------------------------------------ #
    has_mm = _MM_KEYWORDS.search(text) is not None
    has_in = _IN_KEYWORDS.search(text) is not None

    if has_mm and not has_in:
        return ("mm", "title_block")
    if has_in and not has_mm:
        return ("in", "title_block")
    if has_mm and has_in:
        # Conflicting signals — treat as unknown, fall through to Tier 2/3
        pass

    # ------------------------------------------------------------------ #
    # Tier 2 — magnitude inference
    # ------------------------------------------------------------------ #
    if dimension_values:
        abs_vals = [abs(v) for v in dimension_values if v != 0]
        if abs_vals:
            med = _median(abs_vals)
            if med < _SMALL_THRESHOLD:
                return ("in", "magnitude_inference")
            if med > _LARGE_THRESHOLD:
                return ("mm", "magnitude_inference")
            return ("unknown", "magnitude_ambiguous")

    # ------------------------------------------------------------------ #
    # Tier 3 — part_category prior
    # ------------------------------------------------------------------ #
    if part_category:
        cat = part_category.strip().lower()
        if any(k in cat for k in ("us", "aerospace", "asme")):
            return ("in", "category_prior")
        if any(k in cat for k in ("iso", "european")):
            return ("mm", "category_prior")

    return ("unknown", "none")


# Numeric field-name patterns (liberal matching per spec)
_MM_FIELD = re.compile(
    r"(.*_mm$|^nominal$|^diameter$|^depth$|^tolerance$|.*_tol.*|.*tol_.*)",
    re.IGNORECASE,
)


def _is_numeric_dim_field(key: str) -> bool:
    """Return True if *key* looks like a dimension/tolerance field to convert."""
    k = key.lower()
    if k.endswith("_mm"):
        return True
    if k in ("nominal", "diameter", "depth", "tolerance"):
        return True
    if "tol" in k:
        return True
    return False


def _convert_dict(d: dict[str, Any], factor: float) -> None:
    """Recursively multiply all recognised numeric dimension fields by *factor*."""
    for key, val in d.items():
        if isinstance(val, (int, float)) and _is_numeric_dim_field(key):
            d[key] = val * factor
        elif isinstance(val, dict):
            _convert_dict(val, factor)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _convert_dict(item, factor)


def normalize_to_mm(extracted: dict) -> dict:
    """Convert all dimension/tolerance values to mm in-place.

    Parameters
    ----------
    extracted:
        Drawing-extraction JSON matching Lane 8's schema (or any dict that
        contains numeric fields whose names match ``*_mm``, ``diameter``,
        ``depth``, ``nominal``, ``tolerance``, or ``*tol*``).

        Expected top-level keys (all optional):
          units        : 'in' | 'mm' | 'unknown'
          dimensions   : [{nominal_mm, upper_tol_mm, lower_tol_mm, ...}]
          features     : [{diameter_mm, depth_mm, ...}]
          gdt_frames   : [{tolerance_mm, ...}]

    Returns
    -------
    The same dict (mutated in-place) with all applicable fields scaled by 25.4
    when ``units == 'in'``.  Sets ``units='mm'`` and ``conversion_applied=True``.
    Idempotent: if ``conversion_applied`` is already ``True`` the dict is
    returned unchanged regardless of the ``units`` field.
    """
    if extracted.get("conversion_applied"):
        return extracted

    units = extracted.get("units", "unknown")
    if units != "in":
        # Nothing to convert — just record the state.
        extracted.setdefault("conversion_applied", False)
        return extracted

    _convert_dict(extracted, 25.4)

    extracted["units"] = "mm"
    extracted["conversion_applied"] = True
    return extracted
