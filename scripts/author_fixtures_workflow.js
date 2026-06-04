export const meta = {
  name: 'author-nist-fixtures',
  description: 'Clean-room author + verify drawing-read eval fixtures for 5 NIST parts',
  phases: [
    { title: 'Read', detail: 'one reader per drawing.png (ground_truth CLOSED)' },
    { title: 'Verify', detail: 'each fixture must self-score recall==1.0' },
  ],
}

// The 5 parts that need an expected_dims.json authored from the PAGE only.
// nist_stc_06 already has a drawing + GT but NO fixture (review finding #7).
const REPO = 'C:/Users/joshw/CAD Autoresearch/cad-autoresearch'
const PARTS = [
  { id: 'nist_ctc_03', note: 'single-sheet isometric, inch decimals, dense GD&T' },
  { id: 'nist_ftc_07', note: 'View A open box, NOTES say UNITS: INCHES' },
  { id: 'nist_ftc_09', note: 'View A perforated thin plate, dual-unit (in + [mm]); MATERIAL .1195 thk' },
  { id: 'nist_ctc_05', note: 'View 1 of 2 flanged hub/shaft, inch decimals' },
  { id: 'nist_stc_06', note: 'existing asset; review finding #7 — has drawing, no fixture' },
]

// JSON Schema mirroring drawing_extract.EMPTY_SCHEMA so the reader returns a
// validated dict, not prose. Values are AS DRAWN (no unit conversion).
const FIXTURE_SCHEMA = {
  type: 'object',
  required: ['_comment', 'units', 'unit_source', 'views_present',
             'dimensions', 'features', 'gdt_frames', 'title_block'],
  properties: {
    _comment: { type: 'string', description: 'Provenance: derived ONLY from the page, NOT ground_truth/. Note what is absent by design.' },
    units: { type: 'string', enum: ['mm', 'in', 'unknown'] },
    unit_source: { type: 'string', enum: ['title_block', 'tolerance_note', 'magnitude', 'none'] },
    scale: { type: 'string' },
    views_present: { type: 'array', items: { type: 'string' } },
    dimensions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['view', 'type', 'nominal_mm', 'feature_ref'],
        properties: {
          view: { type: 'string' },
          type: { type: 'string', enum: ['linear', 'diameter', 'radius', 'angle', 'depth'] },
          nominal_mm: { type: 'number', description: 'VALUE AS DRAWN (e.g. 0.250 for a .250 inch callout) — NOT converted.' },
          upper_tol_mm: { type: ['number', 'null'] },
          lower_tol_mm: { type: ['number', 'null'] },
          feature_ref: { type: 'string' },
          provenance: { type: 'string', description: 'which view + where on the page this callout sits' },
        },
      },
    },
    features: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'type', 'polarity', 'quantity'],
        properties: {
          id: { type: 'string' },
          type: { type: 'string' },
          polarity: { type: 'string', enum: ['cut', 'add'] },
          diameter_mm: { type: ['number', 'null'], description: 'AS DRAWN, not converted' },
          depth_mm: { type: ['number', 'null'] },
          quantity: { type: 'integer' },
          gdt_refs: { type: 'array', items: { type: 'string' } },
          provenance: { type: 'string' },
        },
      },
    },
    gdt_frames: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'symbol'],
        properties: {
          id: { type: 'string' },
          symbol: { type: 'string' },
          tolerance_mm: { type: ['number', 'null'] },
          material_condition: { type: ['string', 'null'] },
          datum_refs: { type: 'array', items: { type: 'string' } },
          provenance: { type: 'string' },
        },
      },
    },
    title_block: {
      type: 'object',
      properties: {
        material: { type: ['string', 'null'] },
        drawing_number: { type: ['string', 'null'] },
        general_tolerance_note: { type: ['string', 'null'] },
        scale_text: { type: ['string', 'null'] },
      },
    },
  },
}

function readerPrompt(part) {
  return `You are a senior mechanical drafter authoring a CLEAN-ROOM answer key for a
drawing-READ eval. Read the engineering drawing at this exact path with the Read tool
(it renders as an image): ${REPO}/tasks/${part.id}/drawing.png

Context (do not let it override what you actually SEE): ${part.note}

HARD RULES — violating these invalidates the fixture:
1. Author ONLY from what is DRAWN on this page. You are FORBIDDEN to open or read any of:
   ${REPO}/tasks/${part.id}/ground_truth/  (the hidden answer key)
   any .stp / .step file, meta.json, topology.json, make_ground_truth.py for this part.
   Read the drawing.png and NOTHING ELSE under this task dir.
2. Record every value EXACTLY AS DRAWN. If the drawing says Ø.250, record 0.250 — do NOT
   convert to mm. Put the as-drawn number in the *_mm fields and set "units" to what the
   drawing's title block / notes state ("in" if inches, "mm" if millimetres). A downstream
   normalizer scales later; your job is a faithful READ, not a conversion.
3. For EACH dimension/feature/gdt frame add a "provenance" string: which view + roughly
   where on the page the callout sits (e.g. "isometric, upper-left, near the top flange").
   This lets an auditor RE-READ the page to confirm, instead of diffing a banned key.

WHAT TO CAPTURE (match drawing_extract.EMPTY_SCHEMA):
- units + unit_source (title_block | tolerance_note | magnitude | none). If the NOTES block
  says "UNITS: INCHES", units="in", unit_source="title_block".
- views_present (FRONT/TOP/RIGHT/ISOMETRIC/SECTION as applicable — these are usually single
  annotated isometric views).
- dimensions[]: every linear/diameter/radius/angle/depth callout you can read. Do NOT also
  duplicate a hole's diameter here if you put it in features[] (avoid double-counting).
- features[]: holes/bosses/slots/pockets/counterbores. "4X Ø.250" -> ONE feature with
  quantity=4, diameter_mm=0.250, polarity="cut" (a hole removes material). A dashed/hidden
  circle = a bored hole = cut.
- gdt_frames[]: every feature control frame — symbol (position/perpendicularity/flatness/
  profile/...), tolerance value, material condition (MMC/LMC/RFS/null), datum refs.
- title_block: material, drawing_number, general_tolerance_note, scale_text (null if absent).

The "_comment" MUST state: "HAND-AUTHORED from tasks/${part.id}/drawing.png ONLY (NOT
ground_truth/). Values are AS DRAWN (units=<in|mm>, pre-normalization)." and note anything
absent by design.

Return the structured object. Be precise and COMPLETE — read the whole page, every callout.`
}

phase('Read')
const fixtures = await pipeline(
  PARTS,
  (part) => agent(readerPrompt(part), {
    label: `read:${part.id}`,
    phase: 'Read',
    schema: FIXTURE_SCHEMA,
    agentType: 'Explore',
  }).then((fixture) => ({ part, fixture })),
  // Verify stage runs per-item as soon as its read lands (no barrier).
  ({ part, fixture }) => agent(
    `Self-consistency check for the fixture you are given (do NOT re-read files).
A drawing-read scorer pulls "nominal_mm" from dimensions[] and "diameter_mm"/"depth_mm"
from features[]. Scoring the fixture against ITSELF must yield recall==1.0, which it
trivially does if the fixture is internally well-formed. Your job: audit the fixture for
COMPLETENESS and PLAUSIBILITY against the part note, and flag problems.

Part: ${part.id} (${part.note})
Fixture: ${JSON.stringify(fixture, null, 2)}

Check and report:
- Are there dimensions OR features with numeric values? (an empty read scores recall 0 vs
  any real model read — flag if dimensions[] AND features[] are both empty.)
- Any diameter double-counted in BOTH dimensions[] and features[]? (inflates the pool.)
- Do units match what the note implies (inch parts should be units="in")?
- Is _comment present and does it assert page-only provenance?
- Does every dimension/feature carry a "provenance" string?
Return a verdict.`,
    {
      label: `verify:${part.id}`,
      phase: 'Verify',
      schema: {
        type: 'object',
        required: ['part_id', 'ok', 'issues'],
        properties: {
          part_id: { type: 'string' },
          ok: { type: 'boolean', description: 'true if the fixture is complete + well-formed' },
          n_dimensions: { type: 'integer' },
          n_features: { type: 'integer' },
          n_gdt: { type: 'integer' },
          issues: { type: 'array', items: { type: 'string' } },
        },
      },
    }
  ).then((verdict) => ({ part_id: part.id, fixture, verdict })),
)

return { fixtures: fixtures.filter(Boolean) }
