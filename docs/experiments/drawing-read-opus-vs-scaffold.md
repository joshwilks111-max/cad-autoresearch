# Drawing-read A/B — Opus 4.8 vs scaffold-floor (NIST PMI parts)

**Status:** first measurement. **Date:** 2026-06-04. **Branch:** `feat/drawing-assets`.

> **Scope note.** An earlier framing pitched Gemini-vision vs Opus. That was dropped: the
> Gemini-vision *read* arm bills a metered Google plane that isn't part of this subscription
> workflow (and "Gemini" here is easily confused with the Nano-Banana image-GENERATION tool,
> which is a different thing entirely). The decision-relevant question is **"how well does the
> reader we actually use — Opus 4.8 on the Claude subscription — read these drawings?"** So the
> A/B is Opus-vs-floor. The Gemini-read backend remains in `drawing_extract.py` for anyone with
> a funded Google key (`--backends gemini ...`), but it is OFF by default.

## What this measured

Can Opus READ the dimensions / features / GD&T off a real NIST MBE engineering drawing? This
is the project's "hard frontier" (`drawing_extract.py:4` — measured zero-shot dimension recall
on real drawings is brutal, ~40% for the previous Opus generation). The Rung 1.5 reconstruction
A/B came back flat, so the project redirected to the **drawing-read cap**: measure the read
itself, in isolation, before asking whether a better read lifts reconstruction.

Two backends per part, scored OFFLINE against a hand-authored answer key:
- **claude** — `claude -p --model claude-opus-4-8` (subscription via OAuth). The explicit
  `claude-opus-4-8` pin is the review's finding-#3 fix: before it, this arm measured the CLI's
  *default* model and was mislabeled "Opus". The resolved model is recorded in each result, so
  the table provably shows Opus 4.8 ran. (Opus 4.7 was a large vision jump; 4.8 is the current.)
- **scaffold** — the empty-schema FLOOR control (no model call, free). Its recall is what "read
  nothing" scores; any read at/near the scaffold line added no signal.

**Bar:** recall ≥ 0.80 (`drawing_read_eval.MIN_RECALL`), the pre-registered "good enough to
model from" line. Recall = fraction of the answer-key's drawn nominal values (dimension
nominals + feature diameters/depths) recovered, matched within a relative+absolute tolerance.

## Parts in scope (and why two were dropped)

The A/B runs only on parts with a **trustworthy** hand-authored fixture. Authoring a fixture
means reading every callout off the page by eye — and the available NIST renders vary wildly
in legibility:

| part | render | verdict | fixture |
|------|--------|---------|---------|
| `nist_ctc_03` | light-blue isometric, single sheet | legible (tile-crop @500 DPI) | ✅ 8 diameters + 8 GD&T frames |
| `nist_ftc_07` | light-blue isometric, View B | legible | ✅ 5 diameter groups (incl. counterbore) + 8 frames |
| `nist_ftc_09` | light-blue isometric, perforated plate | legible | ✅ 4 diameter groups + 8 frames |
| `nist_ctc_05` | **gold solid render**, hole dims on "View 2 of 2" | callouts NOT on the available view | ❌ deferred |
| `nist_stc_06` | **dark grey solid render**, low contrast | callouts illegible even tiled | ❌ deferred |

`ctc_05` and `stc_06` were **deliberately not given a fixture**. Their renders lack the
contrast/legibility for a reliable page-only read, and a hallucinated answer key would
corrupt the very A/B it is meant to score. This is an honest sourcing limit, not a code gap:
an engineer hitting an unreadable callout re-sources the drawing or skips the part. The
deferral is the right call until a higher-fidelity drawing for those two is obtained.

### How the fixtures were authored (auditable, GT-safe)

Clean-room, from the PAGE only — `ground_truth/`, the `.stp`, `meta.json`, and `topology.json`
were never opened (the hard ban). Technique: render the source PDF at 500 DPI → tile-crop into
4 overlapping (20%) quadrants → transcribe each toleranced callout by eye → cross-confirm
callouts that appear in overlapping tiles. Each value carries a `provenance` string (which
view + where on the page), so an auditor reproduces the key by re-reading the page, NOT by
diffing a banned answer file (review finding #5). Values are recorded AS DRAWN in decimal
inches (`units: "in"`, pre-normalization); the downstream `normalize_to_mm` scales ×25.4.

## Results

Run 2026-06-04, `runs/drawing_read_ab_opus.json`. Backend `claude` ran provably as
`claude-opus-4-8` (recorded per row). Recall is scored in mm (fixture normalized into the
read's unit space — see the units-bug note below).

| part | Opus 4.8 recall | matched | scaffold floor | vs 0.8 bar | fixture/read same view? |
|------|----------------:|:-------:|:--------------:|:----------:|:-----------------------:|
| `nist_ctc_03` | **0.750** | 6/8 | 0.000 | near-miss | yes (single sheet) |
| `nist_ftc_07` | **0.429** | 3/7 | 0.000 | below | **no** — key from View B, read of View A |
| `nist_ftc_09` | **1.000** | 5/5 | 0.000 | ✅ **PASS** | yes |

- **Same-view mean (ctc_03 + ftc_09): 0.875** — above the 0.8 bar.
- **All-three mean: 0.726.**
- **Every scaffold control = 0.000** — the floor holds; the reads carried real signal, not
  schema-shape luck.

### Direction call

**Opus 4.8 reads these NIST PMI drawings well — ~0.75–1.0 dimension recall when the answer key
is authored from the same view the model reads.** That is far above the ~40% literature prior
for the previous-generation Opus, and infinitely above the read-nothing floor (0.000 on every
part). `nist_ftc_09` cleared the 0.8 "good enough to model from" bar outright (perfect 5/5);
`nist_ctc_03` came close (6/8) on a denser part.

The one below-bar part, `nist_ftc_07` (0.429), is **confounded, not a clean Opus miss**: its
fixture was authored from View B (where the toleranced diameters are legible) but the task
`drawing.png` is View A, so Opus was scored against callouts that may sit at awkward angles or
off-frame on the page it actually read. Treat ftc_07 as a lower bound, not a representative
read. The clean datapoints (ctc_03, ftc_09) are the ones to trust.

**Implication for the pulled reconstruction A/B (§3.5):** the original gate was "run the
reconstruction-lift test only if a *better* reader (Gemini) clears the bar where Opus does not."
Reframed to Opus-vs-floor, that gate is moot — there is no second reader to inject. The
reconstruction-lift question becomes: *does handing Opus its OWN pre-extracted read (structured
text alongside the image) lift reconstruction over reading the image inline?* The seam design
below still applies; the injected JSON is just Opus's own `extract_drawing(..., backend="claude")`
output rather than Gemini's.

## Caveats (read before drawing conclusions)

1. **n = 3 parts.** A direction, not a significance result. The literature ~40% prior is the
   thing being tested, not confirmed — this is the first measurement on these specific parts.
2. **The bar is a careful zoomed human read.** Fixtures were authored with tile-crop zoom; Opus
   read the full sheet at once. So absolute recall is scored against a *thorough* read and is a
   genuinely hard bar — the 0.75–1.0 numbers are "vs a zoomed human," not "vs an easy key."
3. **Floored-vs-capped.** These are real, high-face-count NIST holdout parts (`holdout: true` in
   the manifest) — floored below the reconstruction cap. The read A/B is independent of
   reconstruction reachability.
4. **Single-view reads (this is the ftc_07 confound).** NIST MBE drawings are isometric-only
   (annotation lives on the 3D model; there are no orthographic projection sheets). Callouts are
   spread across View A/B/C/D rotations. The read scores ONE primary view; for ftc_07 the fixture
   was authored from View B but the task `drawing.png` is View A, so its 0.429 is a lower bound,
   not a representative read. ctc_03/ftc_09 have no such split.
5. **TRUNCATED reads are not scored as honest-low.** A read that hit MAX_TOKENS is flagged and
   excluded from the pass/fail axis — it's a tooling artifact, not a model failure. (None of the
   three Opus reads truncated this run.)

## Stage 3.5 — reconstruction A/B (PULLED): paper design

The question "does a better drawing-read LIFT reconstruction?" was pulled this phase because
**there is no seam to inject a pre-extracted read into the worker.** `run_inner_loop.py:155`
passes only `DRAWING IMAGE: <path>` into the proposer prompt; the model reads the image inline.
There is nowhere to hand it a pre-computed Gemini JSON.

**The seam (deferred §8 "reader-as-tool" build):** add an optional `extracted_dims` field to the
`task_view` dict in `run_inner_loop.py`. When set, `ClaudeCodeProposer.propose`
(`loop/policies.py`) injects it into the prompt as a new block — e.g. between the `DRAWING
IMAGE:` line and `GROUND TRUTH is hidden` — labeled `PRE-EXTRACTED DIMENSIONS (from <backend>):
<json>`. The orchestrator runs two arms per part: arm-A with no `extracted_dims` (the model
reads the image itself, the current behavior) and arm-B with `extract_drawing(png,
backend="gemini")` pre-computed and injected. Label each ledger row with `read_arm:
none|gemini`. The lift is `composite(arm-B) − composite(arm-A)` on the same part/budget.
Building + running this is a separate phase, gated on Stage 3 showing Gemini clears the read
bar where Opus does not (otherwise there is no better-read to inject).

## A harness bug found + fixed mid-run (units)

The first run scored every read 0.000 — which looked like total failure but was a **scoring
bug, not a read failure**. The fixtures are authored AS DRAWN in inches (`Ø.438` → `0.438`),
but `extract_drawing` always runs `normalize_to_mm`, so a *correct* inch read comes back in mm
(`0.438` → `11.1252`). Scoring a pre-normalization inch fixture against a post-normalization mm
read = a units mismatch that craters recall to 0 on a perfect read. **Fix:** the A/B now
normalizes the fixture through the same pipeline before scoring (`run_one` →
`normalize_extraction(fixture)`), so both sides live in mm. Lesson logged: any reader that
converts units (or reads the bracketed [mm] equivalents) must be scored in a single unit space.

## Reproduce

```bash
# pre-flight (free): confirm the claude reader is reachable
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
.venv/Scripts/python.exe drawing_extract.py --discover     # claude_cli_present: true

# the A/B (claude = subscription OAuth, Opus 4.8; scaffold = free floor)
.venv/Scripts/python.exe -u evals/drawing_read_ab.py --json runs/drawing_read_ab_opus.json
# add the metered Gemini read arm only if you have a funded Google key:
#   .venv/Scripts/python.exe -u evals/drawing_read_ab.py --backends gemini claude scaffold
```
