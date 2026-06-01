# Lane 8 — `drawing_extract.py` (structured drawing reading — the HARD frontier)

**You are building `drawing_extract.py` at the repo root.** Pure addition. Repo:
`C:\Users\joshw\CAD Autoresearch\cad-autoresearch`; `.venv\Scripts\python.exe`. **Be honest about the
ceiling: this is the hardest open problem in AI CAD. Build the SCAFFOLD well; don't over-promise accuracy.**

## Why this matters + the hard facts (from research, do not re-derive)
The drawing track is where AI CAD fails. Measured zero-shot dimension-extraction accuracy on REAL drawings:
**Claude Opus ~40%, Gemini 2.5 Flash ~77%.** So: (1) the drawing-READER should route to Gemini if reachable,
NOT the proposing model; (2) geometric tolerances are the weakest area (~50%); (3) the inch→mm bug is fixed
architecturally by routing every extracted value through Lane 4's `normalize_to_mm` (build to that interface).

## Step 0 — DISCOVER what's reachable, build to it (do this first, report what you found)
- Gemini vision: check for a key — `$GEMINI_API_KEY`, `~/.banana/api_key` (this is likely Google
  Gemini-family but may be image-GEN only — TEST whether it serves a vision/`generateContent` endpoint with
  image input). If a Gemini vision endpoint works → that's the drawing-reader backend.
- If NO Gemini vision is reachable: build the extraction SCAFFOLD (prompt + schema + parser + normalize) and
  document that the backend is pluggable; note that the proposing model (Claude) can be the fallback reader
  at the ~40% ceiling. Do NOT hard-fail — the scaffold + schema + normalization is the durable value.

## Build — the structured-extraction module
A function that takes a drawing PNG and returns the JSON schema below. The CHAIN-OF-THOUGHT ordering in the
prompt is load-bearing (research: it materially improves accuracy) — keep all 6 steps, do not collapse:
```
Step 1: Describe each view (front/top/right/section/iso).
Step 2: List EVERY dimension: numeric value, unit if stated, which view, what feature.
Step 3: For each feature: type (hole/boss/slot/fillet/chamfer/thread/taper) + polarity (cut vs add).
        Use the dashed-line convention: dashed circular projection = cut feature.
Step 4: Every GD&T feature control frame: symbol, tolerance, datum refs.
Step 5: Title block: units, scale, material, general tolerance note, drawing number.
Step 6: Emit JSON.
```
JSON schema (exact — Lane 4's normalize_to_mm consumes this):
```json
{"units":"mm|in|unknown","unit_source":"...","scale":"1:1","views_present":["FRONT","TOP","RIGHT"],
 "dimensions":[{"view":"FRONT","type":"linear|diameter|radius|angle|depth","nominal_mm":25.4,
   "upper_tol_mm":0.1,"lower_tol_mm":-0.1,"feature_ref":"hole_1"}],
 "features":[{"id":"hole_1","type":"through_hole|blind_hole|counterbore|boss|slot|pocket|fillet|chamfer|thread",
   "polarity":"cut|add","diameter_mm":8.0,"depth_mm":null,"quantity":4,"gdt_refs":["gdt_1"]}],
 "gdt_frames":[{"id":"gdt_1","symbol":"position|perpendicularity|flatness|...","tolerance_mm":0.05,
   "material_condition":"MMC|LMC|RFS|null","datum_refs":["A","B"]}],
 "title_block":{"material":null,"drawing_number":null,"general_tolerance_note":null,"scale_text":"1:1"}}
```
- Rasterize source at 300 DPI if given a PDF (pymupdf is installed, used elsewhere).
- After extraction, ALWAYS pass the dict through `normalize_to_mm` (import from Lane 4's `unit_normalize.py`
  if built; else inline the ×25.4-on-inches logic with the idempotency guard). The bug must be impossible.
- CLI: `python drawing_extract.py --drawing tasks/trial_lbracket/drawing.png [--backend gemini|claude|scaffold] [--json]`.
  Importable: `extract_drawing(png_path, backend="auto") -> dict`.

## OPTIONAL sub-feature (gated — attempt, report, don't block the lane): AP242 PMI oracle
`from OCP.XCAFDoc import XCAFDoc_DimTolTool` + `STEPCAFControl_Reader` IMPORT OK in this env (tested). Attempt
the native path: `reader.SetGDTMode(True)`, transfer to an XCAF doc, `DimTolTool.GetDimensionLabels(labels)`,
read `XCAFDimTolObjects_DimensionObject.GetValue()`. Test it on a NIST part with semantic PMI (e.g.
`tasks/nist_stc_06/ground_truth/result.step` or `tasks/nist_ftc_11/...`). If `GetDimensionLabels` returns
NON-EMPTY → you have a native PMI oracle (a ground-truth dimension list to VALIDATE the VLM extraction
against — NOT to grade with). If it returns empty (tessellated-only PMI) or the API is incomplete → document
that and note the NIST SFA subprocess as the fallback (don't build the Tcl subprocess in this lane). This is
a 30-min experiment with high upside; report the result either way.

## Self-test (must pass, include in report)
1. `python drawing_extract.py --drawing tasks/trial_lbracket/drawing.png --json` → returns the schema
   populated (the L-bracket: ~6 dims, units, 6+ features incl. holes with polarity=cut). Paste it. Judge it
   against the KNOWN part (spec.md: 120×60×44, Ø8 holes, gusset) — how accurate was it?
2. Feed an inch-y dict through normalize_to_mm → values ×25.4. (Confirms the bug-proofing.)
3. The AP242 PMI experiment result (non-empty labels? or empty/unavailable?) — paste what GetDimensionLabels
   returned.
4. `git status` shows only the new file(s).

## Report back (be honest)
File(s) created; what vision backend was actually reachable (Gemini? only banana image-gen? Claude
fallback?); the extraction self-test output + YOUR honest accuracy judgment vs the known L-bracket; the
AP242-PMI experiment result; the ceiling caveat. This lane's DURABLE value is the schema + prompt +
normalize integration even if no strong vision backend is wired today. Effort ~1-2 days; flag if the vision
backend is the blocker.
