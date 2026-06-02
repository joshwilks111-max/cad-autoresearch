#!/usr/bin/env python3
"""drawing_extract.py -- structured engineering-drawing reading (Lane 8).

THE HARD FRONTIER. This is the single hardest open problem in AI-to-CAD. Measured
zero-shot dimension-extraction accuracy on REAL drawings is brutal:
    Claude Opus ~40%,  Gemini 2.5 Flash ~77%,  GD&T ~50% (the weakest area).
So this module is built as a *scaffold* whose durable value is the schema + the
chain-of-thought prompt + the unit-normalization integration -- NOT a promise of
accuracy. The vision backend is pluggable.

Architecture (the load-bearing parts):
  1. A chain-of-thought prompt with 6 ordered steps. Research shows the ordering
     materially improves accuracy; we keep all 6 steps and never collapse them.
  2. A fixed JSON schema that Lane 4's `normalize_to_mm` consumes verbatim.
  3. The drawing-READER routes to Gemini when reachable (the stronger reader),
     NOT to the proposing model. Claude is the ~40%-ceiling fallback.
  4. EVERY extracted dict is passed through `normalize_to_mm` so the recurring
     inch->mm bug (cost real time on STC-06) becomes architecturally impossible.

Public API:
    extract_drawing(png_path, backend="auto") -> dict   # always schema-shaped
    EXTRACTION_PROMPT                                    # the 6-step CoT prompt
    EMPTY_SCHEMA                                         # a blank, valid result
    probe_ap242_pmi(step_path) -> dict                   # optional native-PMI oracle

CLI:
    python drawing_extract.py --drawing tasks/trial_lbracket/drawing.png [--json]
                              [--backend auto|gemini|claude|scaffold]
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# 1. THE SCHEMA  (exact -- Lane 4's normalize_to_mm consumes this)
# --------------------------------------------------------------------------- #
# An empty-but-valid result. Backends fill it in; the scaffold returns it as-is.
EMPTY_SCHEMA: dict[str, Any] = {
    "units": "unknown",
    "unit_source": "none",
    "scale": "unknown",
    "views_present": [],
    "dimensions": [],   # {view,type,nominal_mm,upper_tol_mm,lower_tol_mm,feature_ref}
    "features": [],     # {id,type,polarity,diameter_mm,depth_mm,quantity,gdt_refs}
    "gdt_frames": [],   # {id,symbol,tolerance_mm,material_condition,datum_refs}
    "title_block": {
        "material": None,
        "drawing_number": None,
        "general_tolerance_note": None,
        "scale_text": None,
    },
    # provenance (added by this module, ignored by normalize_to_mm)
    "_backend": None,
    "_backend_detail": None,
    "_warnings": [],
}


def empty_result() -> dict[str, Any]:
    """A fresh deep copy of the blank schema (never share the module-level dict)."""
    return copy.deepcopy(EMPTY_SCHEMA)


# --------------------------------------------------------------------------- #
# 2. THE CHAIN-OF-THOUGHT PROMPT  (6 ordered steps -- do NOT collapse)
# --------------------------------------------------------------------------- #
SCHEMA_HINT = json.dumps(
    {
        "units": "mm|in|unknown",
        "unit_source": "title_block|tolerance_note|magnitude|none",
        "scale": "1:1",
        "views_present": ["FRONT", "TOP", "RIGHT"],
        "dimensions": [
            {
                "view": "FRONT",
                "type": "linear|diameter|radius|angle|depth",
                "nominal_mm": 25.4,
                "upper_tol_mm": 0.1,
                "lower_tol_mm": -0.1,
                "feature_ref": "hole_1",
            }
        ],
        "features": [
            {
                "id": "hole_1",
                "type": "through_hole|blind_hole|counterbore|boss|slot|pocket|fillet|chamfer|thread",
                "polarity": "cut|add",
                "diameter_mm": 8.0,
                "depth_mm": None,
                "quantity": 4,
                "gdt_refs": ["gdt_1"],
            }
        ],
        "gdt_frames": [
            {
                "id": "gdt_1",
                "symbol": "position|perpendicularity|flatness|parallelism|concentricity|runout|profile",
                "tolerance_mm": 0.05,
                "material_condition": "MMC|LMC|RFS|null",
                "datum_refs": ["A", "B"],
            }
        ],
        "title_block": {
            "material": None,
            "drawing_number": None,
            "general_tolerance_note": None,
            "scale_text": "1:1",
        },
    },
    indent=2,
)

EXTRACTION_PROMPT = f"""You are a senior mechanical drafter reading a 2D engineering \
drawing to reconstruct the part in CAD. Work through the drawing methodically. The \
ORDER of the following steps is important -- do every step, in order, before you emit \
JSON. Reason step by step in your head; then output ONLY the final JSON object.

Step 1 -- VIEWS. Describe each view present (front / top / right / section / isometric). \
Note the projection convention (first- vs third-angle) if discernible.

Step 2 -- DIMENSIONS. List EVERY dimension you can read. For each: the numeric value, \
the unit IF the drawing states one (do not assume), which view it appears in, and what \
feature it dimensions. Include diameters (Ø), radii (R), linear, angular, and depth.

Step 3 -- FEATURES. For each feature, give its type \
(hole / boss / slot / fillet / chamfer / thread / taper / pocket / counterbore) and its \
POLARITY -- whether it removes material (cut) or adds it (add). Use the dashed-line \
convention: a dashed circular projection (a hidden circle) is a hole bored INTO the body \
-> polarity = cut. A solid circle on a raised feature is typically a boss -> add.

Step 4 -- GD&T. Read every geometric tolerance feature control frame: the symbol \
(position, perpendicularity, flatness, parallelism, concentricity, runout, profile, ...), \
the tolerance value, the material condition modifier (MMC / LMC / RFS), and the datum \
references. GD&T is the hardest part of the drawing -- if a frame is ambiguous, record \
your best read and flag low confidence rather than omitting it.

Step 5 -- TITLE BLOCK. Read the title block: the units of measure, the scale, the \
material, the general/default tolerance note (e.g. "UNLESS OTHERWISE SPECIFIED +/-0.005 IN"), \
and the drawing number. The units here are authoritative -- prefer them over guessing.

Step 6 -- EMIT JSON. Output a single JSON object matching EXACTLY this schema (same keys; \
use null for unknown numerics; put every length/tolerance in the *_mm fields using the \
NUMERIC VALUE AS DRAWN -- do not convert units yourself, just record `units` faithfully \
and a downstream normalizer will scale). Schema:

{SCHEMA_HINT}

Output ONLY the JSON object, no prose, no markdown fences."""


# --------------------------------------------------------------------------- #
# 3. UNIT NORMALIZATION  (import Lane 4 if present; else inline fallback)
# --------------------------------------------------------------------------- #
_REPO = Path(__file__).resolve().parent


def _inline_normalize_to_mm(extracted: dict) -> dict:
    """Liberal, idempotent inch->mm normalizer. Used only when unit_normalize.py
    (Lane 4) is not yet built. Mirrors Lane 4's contract: if units=='in', multiply
    every length/tol/diameter/depth field by 25.4 in place, set units='mm',
    conversion_applied=True. Guarded so it never double-converts."""
    if not isinstance(extracted, dict):
        return extracted
    if extracted.get("conversion_applied"):
        return extracted  # idempotency guard
    units = str(extracted.get("units", "unknown")).lower()
    if units != "in":
        # mm or unknown -> leave values; just record state
        extracted.setdefault("conversion_applied", False)
        return extracted

    factor = 25.4

    def _scale_numeric_fields(obj: dict) -> None:
        for k, v in list(obj.items()):
            if isinstance(v, bool) or v is None:
                continue
            kl = k.lower()
            is_len = (
                kl.endswith("_mm")
                or "diameter" in kl
                or "depth" in kl
                or "nominal" in kl
                or "tolerance" in kl
                or "radius" in kl
            )
            if is_len and isinstance(v, (int, float)):
                obj[k] = v * factor

    for d in extracted.get("dimensions", []) or []:
        if isinstance(d, dict):
            _scale_numeric_fields(d)
    for f in extracted.get("features", []) or []:
        if isinstance(f, dict):
            _scale_numeric_fields(f)
    for g in extracted.get("gdt_frames", []) or []:
        if isinstance(g, dict):
            _scale_numeric_fields(g)

    extracted["units"] = "mm"
    extracted["conversion_applied"] = True
    extracted.setdefault("_warnings", []).append(
        "inline normalize: scaled in->mm x25.4 (unit_normalize.py not present)"
    )
    return extracted


def _get_normalizer():
    """Return the best-available normalize_to_mm callable + a label."""
    try:
        if str(_REPO) not in sys.path:
            sys.path.insert(0, str(_REPO))
        from unit_normalize import normalize_to_mm as _lane4  # type: ignore
        return _lane4, "lane4"
    except Exception:
        return _inline_normalize_to_mm, "inline"


def normalize_extraction(extracted: dict) -> dict:
    """Always-applied final step. Routes the dict through Lane 4's normalize_to_mm
    (if built) or the inline fallback. The inch->mm bug must be impossible."""
    fn, label = _get_normalizer()
    out = fn(extracted)
    if isinstance(out, dict):
        out.setdefault("_normalizer", label)
    return out


# --------------------------------------------------------------------------- #
# 4. RASTERIZATION  (PDF -> PNG @ 300 DPI via pymupdf)
# --------------------------------------------------------------------------- #
def _to_png_bytes(drawing_path: str | Path, dpi: int = 300) -> tuple[bytes, str]:
    """Return (png_bytes, mime). Rasterizes a PDF at `dpi`; passes images through."""
    p = Path(drawing_path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        import fitz  # pymupdf
        doc = fitz.open(str(p))
        try:
            page = doc.load_page(0)
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png"), "image/png"
        finally:
            doc.close()
    # raster image -> read bytes; normalize mime
    data = p.read_bytes()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
    return data, mime


# --------------------------------------------------------------------------- #
# 5. BACKENDS
# --------------------------------------------------------------------------- #
def _read_gemini_key() -> str | None:
    """Read a Gemini/Google key WITHOUT ever returning it to a caller that logs.
    Order: $GEMINI_API_KEY, $GOOGLE_API_KEY, ~/.banana/api_key. Returns the raw
    string for use inside this module only (never printed)."""
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        v = os.environ.get(env)
        if v and v.strip():
            return v.strip()
    keyfile = Path(os.path.expanduser("~/.banana/api_key"))
    if keyfile.exists():
        try:
            txt = keyfile.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            pass
    return None


# Gemini vision models to try, strongest-first. 2.5 Flash is the measured leader
# for drawing reading (~77%); 1.5 Flash/Pro are fallbacks for older keys.
_GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
)


def _gemini_generate(png_b64: str, mime: str, key: str, *, probe_only: bool = False
                     ) -> tuple[bool, str, str]:
    """Call Gemini generateContent with the image + prompt over stdlib urllib
    (requests is NOT installed in this env). Returns (ok, model_used, text_or_err).
    If probe_only, sends a trivial 1-token request just to confirm the endpoint
    serves vision generateContent for this key."""
    import urllib.request
    import urllib.error

    prompt = "Reply with the single word OK." if probe_only else EXTRACTION_PROMPT
    gen_cfg: dict[str, Any] = {"temperature": 0.0}
    if probe_only:
        # gemini-2.5-* spends output budget on internal "thinking"; too small a
        # cap starves the visible answer and returns empty parts. 256 is enough
        # for the one-word probe reply to surface.
        gen_cfg["maxOutputTokens"] = 256
    else:
        # The L-bracket-class extraction is long, and gemini-2.5-* also spends
        # output budget on internal "thinking" -- 8192 truncates the JSON
        # mid-string (observed). Give generous headroom and force a clean JSON
        # response so there is no markdown/preamble to chew tokens.
        gen_cfg["maxOutputTokens"] = 16384
        gen_cfg["responseMimeType"] = "application/json"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": png_b64}},
                ]
            }
        ],
        "generationConfig": gen_cfg,
    }
    last_err = "no model tried"
    for model in _GEMINI_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        data = json.dumps(body).encode("utf-8")
        # one retry on transient failures (429/500/503, empty body, timeout)
        for attempt in range(2):
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                cands = payload.get("candidates") or []
                if not cands:
                    last_err = (
                        f"{model}: empty candidates ({json.dumps(payload)[:200]})"
                    )
                    continue  # retry once
                cand0 = cands[0]
                finish = cand0.get("finishReason")
                parts = (cand0.get("content") or {}).get("parts") or []
                text = "".join(pt.get("text", "") for pt in parts).strip()
                if text and finish == "MAX_TOKENS":
                    # truncated -- annotate so callers can warn instead of
                    # silently returning a broken/empty parse
                    return True, f"{model}|TRUNCATED(MAX_TOKENS)", text
                if text:
                    return True, model, text
                last_err = f"{model}: candidate had no text (finishReason={finish})"
                # fall through to retry
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8")[:300]
                except Exception:
                    detail = ""
                last_err = f"{model}: HTTP {e.code} {detail}"
                if e.code in (401, 403):
                    # auth problem is global -- stop trying further models
                    return False, model, last_err
                if e.code in (404, 400):
                    break  # model/endpoint unavailable for this key; next model
                # 429/500/503 -> fall through and retry once
            except Exception as e:  # noqa: BLE001
                last_err = f"{model}: {type(e).__name__}: {e}"
                # transient (timeout/conn) -> retry once
    return False, "", last_err


def _strip_json(text: str) -> str:
    """Pull the JSON object out of a model reply (handles ```json fences / prose)."""
    t = text.strip()
    if t.startswith("```"):
        # drop the first fence line and any trailing fence
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    # fall back to first { ... last }
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j != -1 and j > i:
            t = t[i : j + 1]
    return t


def _loads_tolerant(text: str) -> dict:
    """json.loads, but salvage a TRUNCATED object (Gemini cut at MAX_TOKENS).
    Strategy: try strict parse; on failure, progressively trim trailing chars
    and close open brackets/quotes until it parses. Best-effort -- returns the
    largest valid prefix object it can recover (so we keep the dims read so far)."""
    t = _strip_json(text)
    try:
        return json.loads(t)
    except Exception:
        pass
    # Salvage: walk back to the last complete top-level array/object element and
    # close the structure. Track bracket depth over a sanitized scan.
    best: dict | None = None
    # try truncating at each closing brace/bracket from the end, then balance
    for cut in range(len(t), 0, -1):
        if t[cut - 1] not in "}],":
            continue
        frag = t[:cut].rstrip().rstrip(",")
        # balance brackets
        opens = frag.count("{") - frag.count("}")
        opensq = frag.count("[") - frag.count("]")
        if opens < 0 or opensq < 0:
            continue
        candidate = frag + ("]" * opensq) + ("}" * opens)
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                best = obj
                break
        except Exception:
            continue
    if best is not None:
        return best
    raise ValueError("could not salvage JSON")


def _coerce_to_schema(parsed: dict) -> dict:
    """Merge a model's parsed dict onto the empty schema so downstream code always
    sees every key, with sane types."""
    out = empty_result()
    if not isinstance(parsed, dict):
        return out
    for k in ("units", "unit_source", "scale"):
        if parsed.get(k):
            out[k] = parsed[k]
    if isinstance(parsed.get("views_present"), list):
        out["views_present"] = [str(v).upper() for v in parsed["views_present"]]
    for k in ("dimensions", "features", "gdt_frames"):
        v = parsed.get(k)
        if isinstance(v, list):
            out[k] = [x for x in v if isinstance(x, dict)]
    tb = parsed.get("title_block")
    if isinstance(tb, dict):
        for kk in ("material", "drawing_number", "general_tolerance_note", "scale_text"):
            if kk in tb:
                out["title_block"][kk] = tb[kk]
    return out


def _backend_gemini(png_bytes: bytes, mime: str) -> dict | None:
    """Try the Gemini vision backend. Returns a schema dict on success, else None."""
    key = _read_gemini_key()
    if not key:
        return None
    b64 = base64.b64encode(png_bytes).decode("ascii")
    ok, model, text = _gemini_generate(b64, mime, key, probe_only=False)
    if not ok:
        # record nothing here; caller logs the reachability separately
        return None
    truncated = "TRUNCATED" in model
    try:
        parsed = _loads_tolerant(text)
    except Exception as e:  # noqa: BLE001
        res = empty_result()
        res["_backend"] = "gemini"
        res["_backend_detail"] = f"{model}: JSON parse failed: {e}"
        res["_warnings"].append("gemini returned non-JSON; emitting empty schema")
        res["_raw_text"] = text[:2000]
        return res
    res = _coerce_to_schema(parsed)
    if truncated:
        res["_warnings"].append(
            "gemini response hit MAX_TOKENS; recovered the valid JSON prefix "
            "(some dimensions/features near the end may be missing)"
        )
    res["_backend"] = "gemini"
    res["_backend_detail"] = model
    return res


def _backend_claude(png_path: str | Path) -> dict | None:
    """Fallback reader: the local `claude` CLI (subscription) at the ~40% ceiling.
    Only used if the binary is reachable. Best-effort; returns None if unreachable."""
    import shutil
    import subprocess

    exe = shutil.which("claude")
    if not exe:
        return None
    # Keep this `claude` spawn on the subscription too (it's not on the orchestrator hot
    # path, but "every place that spawns claude" must scrub the billing vars). Import the
    # shared scrub lazily with a safe fallback so this module stays importable standalone.
    try:
        if str(_REPO) not in sys.path:
            sys.path.insert(0, str(_REPO))
        from loop.billing import subscription_env  # type: ignore
        _child_env = subscription_env()
    except Exception:  # noqa: BLE001
        _child_env = {k: v for k, v in os.environ.items()
                      if k.lower() not in ("anthropic_api_key", "anthropic_auth_token",
                                           "anthropic_base_url")}
    # We pass the image by path in the prompt; the CLI reads local files.
    p = Path(png_path).resolve()
    prompt = (
        f"Read the engineering drawing at this local path: {p}\n\n"
        + EXTRACTION_PROMPT
    )
    try:
        proc = subprocess.run(
            [exe, "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            env=_child_env,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        parsed = json.loads(_strip_json(proc.stdout))
    except Exception:  # noqa: BLE001
        res = empty_result()
        res["_backend"] = "claude"
        res["_backend_detail"] = "claude CLI returned non-JSON"
        res["_warnings"].append("claude CLI reply was not JSON; emitting empty schema")
        return res
    res = _coerce_to_schema(parsed)
    res["_backend"] = "claude"
    res["_backend_detail"] = "claude CLI (text)"
    return res


def _backend_scaffold(reason: str) -> dict:
    """The durable artifact: a valid, empty schema + the reason no VLM was used.
    The prompt + schema + normalize integration are the real deliverable."""
    res = empty_result()
    res["_backend"] = "scaffold"
    res["_backend_detail"] = reason
    res["_warnings"].append(
        "no vision backend reachable; returned empty schema. "
        "Wire GEMINI_API_KEY (preferred) or the claude CLI to populate it."
    )
    return res


# --------------------------------------------------------------------------- #
# 6. PUBLIC ENTRY POINT
# --------------------------------------------------------------------------- #
def extract_drawing(png_path: str | Path, backend: str = "auto") -> dict:
    """Read an engineering drawing (PNG/JPG/PDF) and return the structured schema.

    backend: 'auto'   -> gemini if reachable, else claude CLI, else scaffold
             'gemini' -> Gemini vision only (scaffold-shaped error if unreachable)
             'claude' -> claude CLI only
             'scaffold' -> never call a VLM; return the empty schema (offline)

    The result ALWAYS conforms to EMPTY_SCHEMA's shape and is ALWAYS passed through
    normalize_to_mm before return, so the inch->mm bug cannot occur downstream.
    """
    p = Path(png_path)
    if not p.exists():
        raise FileNotFoundError(f"drawing not found: {p}")

    backend = (backend or "auto").lower()
    result: dict | None = None

    if backend == "scaffold":
        result = _backend_scaffold("backend=scaffold requested (no VLM call)")
    else:
        # rasterize once (cheap) so every image backend shares the bytes
        try:
            png_bytes, mime = _to_png_bytes(p, dpi=300)
        except Exception as e:  # noqa: BLE001
            return normalize_extraction(
                _backend_scaffold(f"rasterization failed: {type(e).__name__}: {e}")
            )

        if backend in ("auto", "gemini"):
            result = _backend_gemini(png_bytes, mime)
        if result is None and backend in ("auto", "claude"):
            result = _backend_claude(p)
        if result is None:
            why = (
                "no GEMINI/GOOGLE key and no reachable claude CLI"
                if backend == "auto"
                else f"backend={backend} unreachable"
            )
            result = _backend_scaffold(why)

    # ---- THE NON-NEGOTIABLE FINAL STEP: normalize units to mm ----
    return normalize_extraction(result)


def discover_backends() -> dict[str, Any]:
    """Report (without leaking secrets) which backends are reachable right now.
    Used by the CLI's --discover and by the self-test."""
    import shutil

    key = _read_gemini_key()
    info: dict[str, Any] = {
        "gemini_key_present": key is not None,
        "gemini_key_source": None,
        "gemini_vision_reachable": None,
        "gemini_vision_detail": None,
        "claude_cli_present": shutil.which("claude") is not None,
        "requests_installed": False,
    }
    try:
        import requests  # noqa: F401
        info["requests_installed"] = True
    except Exception:
        info["requests_installed"] = False

    if key is not None:
        for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            if os.environ.get(env):
                info["gemini_key_source"] = f"env:{env}"
                break
        else:
            info["gemini_key_source"] = "file:~/.banana/api_key"
        # live reachability probe with a 1x1 transparent PNG (tiny, cheap)
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYGAA"
            "AAAEAAH2FzhVAAAAAElFTkSuQmCC"
        )
        ok, model, detail = _gemini_generate(
            tiny_png_b64, "image/png", key, probe_only=True
        )
        info["gemini_vision_reachable"] = ok
        # the probe uses a tiny token cap on purpose, so a MAX_TOKENS marker here
        # is expected and meaningless -- strip it from the reachability label.
        info["gemini_vision_detail"] = (model.split("|")[0] if ok else detail)
    return info


# --------------------------------------------------------------------------- #
# 7. OPTIONAL: AP242 native PMI oracle  (XCAFDoc_DimTolTool)
# --------------------------------------------------------------------------- #
def probe_ap242_pmi(step_path: str | Path) -> dict[str, Any]:
    """Open a STEP via STEPCAFControl_Reader with GDT mode on, transfer to an XCAF
    document, and ask XCAFDoc_DimTolTool for its dimension / tolerance / datum
    labels. If GetDimensionLabels returns NON-EMPTY, the file carries SEMANTIC
    (machine-readable) PMI and we have a native ground-truth dimension list to
    VALIDATE a VLM extraction against (NOT to grade with). If empty, the PMI is
    tessellated-only (or absent) and the NIST STEP File Analyzer (SFA) Tcl
    subprocess would be the fallback (not built in this lane).

    Returns a small report dict; never raises (captures errors into the dict).
    NOTE: this is a capability probe -- it counts labels, it does not read
    geometry into any candidate. Do not point it at a hidden answer key you are
    meant to reconstruct."""
    report: dict[str, Any] = {
        "step_path": str(step_path),
        "read_status": None,
        "n_dimension_labels": None,
        "n_geomtol_labels": None,
        "n_datum_labels": None,
        "first_dimension_value": None,
        "has_semantic_pmi": None,
        "error": None,
    }
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDF import TDF_LabelSequence

        doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
        reader = STEPCAFControl_Reader()
        reader.SetGDTMode(True)  # read semantic GD&T
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            report["read_status"] = f"ReadFile != RetDone ({status})"
            return report
        ok = reader.Transfer(doc)
        report["read_status"] = "transferred" if ok else "transfer-returned-false"

        dimtol = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())

        dim_labels = TDF_LabelSequence()
        dimtol.GetDimensionLabels(dim_labels)
        report["n_dimension_labels"] = dim_labels.Length()

        gt_labels = TDF_LabelSequence()
        dimtol.GetGeomToleranceLabels(gt_labels)
        report["n_geomtol_labels"] = gt_labels.Length()

        dat_labels = TDF_LabelSequence()
        dimtol.GetDatumLabels(dat_labels)
        report["n_datum_labels"] = dat_labels.Length()

        report["has_semantic_pmi"] = dim_labels.Length() > 0

        # if there is at least one dimension, read its value (oracle, not grader)
        if dim_labels.Length() > 0:
            try:
                from OCP.XCAFDoc import XCAFDoc_Dimension
                lab = dim_labels.Value(1)
                dim_attr = XCAFDoc_Dimension()
                if lab.FindAttribute(XCAFDoc_Dimension.GetID_s(), dim_attr):
                    obj = dim_attr.GetObject()
                    report["first_dimension_value"] = float(obj.GetValue())
            except Exception as e:  # noqa: BLE001
                report["first_dimension_value"] = f"<read failed: {e}>"
    except Exception as e:  # noqa: BLE001
        report["error"] = f"{type(e).__name__}: {e}"
    return report


# --------------------------------------------------------------------------- #
# 8. CLI
# --------------------------------------------------------------------------- #
def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Structured engineering-drawing extraction (Lane 8)."
    )
    ap.add_argument("--drawing", help="path to drawing PNG/JPG/PDF")
    ap.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "gemini", "claude", "scaffold"],
        help="vision backend (default auto)",
    )
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument(
        "--discover", action="store_true", help="report reachable backends and exit"
    )
    ap.add_argument(
        "--pmi-probe",
        metavar="STEP",
        help="run the AP242 native-PMI probe on a STEP file and exit",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    if args.discover:
        print(json.dumps(discover_backends(), indent=2))
        return 0

    if args.pmi_probe:
        print(json.dumps(probe_ap242_pmi(args.pmi_probe), indent=2))
        return 0

    if not args.drawing:
        print("error: --drawing is required (or use --discover / --pmi-probe)",
              file=sys.stderr)
        return 2

    result = extract_drawing(args.drawing, backend=args.backend)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        be = result.get("_backend")
        n_dim = len(result.get("dimensions", []))
        n_feat = len(result.get("features", []))
        n_gdt = len(result.get("gdt_frames", []))
        print(f"backend={be} ({result.get('_backend_detail')})")
        print(f"units={result.get('units')} ({result.get('unit_source')})  "
              f"scale={result.get('scale')}")
        print(f"views={result.get('views_present')}")
        print(f"dimensions={n_dim}  features={n_feat}  gdt_frames={n_gdt}")
        for w in result.get("_warnings", []):
            print(f"  warn: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
