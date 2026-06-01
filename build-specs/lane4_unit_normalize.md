# Lane 4 — `unit_normalize.py` (kill the inch→mm bug architecturally)

**You are building one file: `unit_normalize.py` at the repo root.** Pure addition. Repo:
`C:\Users\joshw\CAD Autoresearch\cad-autoresearch`; `.venv\Scripts\python.exe`.

## Goal
The recurring, painful drawing-track bug: a drawing in INCHES whose dimensions need ×25.4, which the modeler
missed (cost real time on STC-06). Make this bug ARCHITECTURALLY IMPOSSIBLE: a deterministic function that
detects units and normalizes ALL dimension values to mm BEFORE any value reaches build123d. This is the
companion to Lane 8 (drawing extraction) but is standalone + dependency-free + independently testable.

## Build
```python
def detect_units(*, title_block_text: str = "", explicit: str|None = None,
                 dimension_values: list[float] | None = None,
                 part_category: str|None = None) -> tuple[str, str]:
    """Return (units, source). units in {'mm','in','unknown'}. Three-tier heuristic:
    Tier 1 (strongest): explicit kw in title_block_text — 'MM'/'MILLIMET' -> mm;
      'INCH'/'\"'/' IN ' -> in; a tolerance note like '±0.005 IN' -> in, '±0.13 MM' -> mm.
      If `explicit` arg given, trust it.
    Tier 2: dimension magnitude sanity (only if Tier 1 silent) — median(|dims|): <12 & machined -> 'in';
      >15 -> 'mm'; 6-15 -> ambiguous (return 'unknown' unless a prior).
    Tier 3: part_category prior — 'us'/'aerospace'/'asme' -> in; 'iso'/'european' -> mm.
    Return ('unknown', 'none') if nothing fires."""

def normalize_to_mm(extracted: dict) -> dict:
    """extracted = the drawing-extraction JSON (see Lane 8 schema): {units, dimensions:[{nominal_mm,
    upper_tol_mm,lower_tol_mm,...}], features:[{diameter_mm,depth_mm,...}], gdt_frames:[{tolerance_mm}]}.
    If extracted['units']=='in', multiply EVERY numeric dim/tol/diameter/depth field by 25.4 IN PLACE and
    set units='mm', conversion_applied=True. If 'mm' or 'unknown', return unchanged (record the state).
    Idempotent: never double-convert (guard on a 'conversion_applied' flag)."""
```
Pure Python, numpy optional (only for median). No build123d/OCC needed. The schema field names match Lane 8's
JSON; if Lane 8 isn't built yet, accept any dict and convert any key matching `*_mm`/`diameter`/`depth`/
`nominal`/`tolerance` numerics — be liberal but idempotent.

## Self-test (must pass, include in report)
1. `detect_units(title_block_text="UNLESS OTHERWISE SPECIFIED ±0.005 IN")` → ('in','tolerance_note').
2. `detect_units(title_block_text="ALL DIMS MM")` → ('mm', ...).
3. `detect_units(dimension_values=[0.5,1.25,2.0,3.5])` (no text) → ('in','magnitude_inference').
4. `normalize_to_mm({'units':'in','dimensions':[{'nominal_mm':1.0,'upper_tol_mm':0.01,'lower_tol_mm':-0.01}]})`
   → nominal 25.4, tol ±0.254, units='mm'; and running it AGAIN does NOT change it (idempotent).
5. `git status` shows only the new file.

## Report back
File created; the 5 self-test outputs (paste them); confirm idempotency. Effort ~2-4h. This is a hard
architectural fix — once everything routes dims through normalize_to_mm, the ×25.4 bug cannot recur.
