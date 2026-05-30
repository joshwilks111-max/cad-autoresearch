"""
feedback.py — compact, actionable feedback for the next attempt.

The agent doesn't need the full raw metric dump; it needs to know WHICH layer
failed and WHAT that failure usually means in CAD terms. This turns a RunResult +
RewardResult into a short markdown report plus diagnostic hints that map a failing
layer to likely root causes (the failure modes the literature keeps finding:
misread dimensions, feature-polarity errors, missed fillets/holes). Keep it
terse — it is fed back into the context window every turn.
"""
from __future__ import annotations

from .reward import RewardResult
from .runner import RunResult


def hints(rw: RewardResult) -> list[str]:
    h: list[str] = []
    raw = rw.raw

    if rw.body == 0:
        return ["No valid solid was produced. Check that `result` is assigned and "
                "the build did not raise — read the stderr above."]

    vc, vg = raw.get("volume_candidate"), raw.get("volume_gt")
    if rw.volume < 0.9 and vc and vg:
        if vc < vg * 0.10:
            # Candidate is a tiny fragment of GT — a valid solid built, but it
            # collapsed. Almost always a failed OpenCASCADE boolean (e.g. a
            # sphere/cone fused tangent, or sequential cuts that ate the part),
            # NOT a normal "missing feature". Name it so the fix is obvious.
            h.append(f"SOLID COLLAPSED: candidate volume is only {vc/vg*100:.1f}% of "
                     "ground truth — the part built but is a fragment. This is almost "
                     "always a FAILED BOOLEAN (OpenCASCADE returned a degenerate result "
                     "without erroring), not a missing feature. Build independent "
                     "sub-bodies and fuse once at the end; overlap ADD features into "
                     "their host (never tangent); batch SUBTRACT cuts into one compound; "
                     "use revolve for cones/spheres instead of primitive booleans.")
        elif vc > vg * 1.10:
            h.append(f"Volume is {((vc/vg)-1)*100:.0f}% OVER ground truth. Likely an "
                     "extra body, a pocket modelled as a boss, or a hole you didn't "
                     "cut. Check feature POLARITY (cut vs add).")
        elif vc < vg * 0.90:
            h.append(f"Volume is {(1-(vc/vg))*100:.0f}% UNDER ground truth. Likely a "
                     "missing feature, an over-aggressive cut, or wrong wall thickness.")

    bc, bg = raw.get("bbox_candidate"), raw.get("bbox_gt")
    if rw.bbox < 0.9 and bc and bg:
        h.append(f"Bounding box mismatch: candidate {[round(x,1) for x in bc]} vs GT "
                 f"{[round(x,1) for x in bg]} (sorted mm). Re-check overall dimensions "
                 "and unit conversion (drawing in inches -> mm?).")

    sc, sg = raw.get("topology_candidate"), raw.get("topology_gt")
    if rw.topology < 0.99 and sc and sg:
        diffs = {k: (sc.get(k), sg.get(k)) for k in set(sc) | set(sg)
                 if sc.get(k) != sg.get(k)}
        if diffs:
            h.append(f"Topology differs (candidate vs GT): {diffs}. A face/edge-count "
                     "gap usually means a missing fillet/chamfer, a missed hole, or a "
                     "feature merged where it should be separate.")

    if rw.iou < 0.7:
        h.append("Low volumetric IoU even after pose alignment: the gross shape is off. "
                 "Step back and re-read the primary profile / sketch before tweaking "
                 "details.")
    elif rw.chamfer < 0.7:
        h.append("Gross shape is close but surfaces are off (high Chamfer): suspect "
                 "fillet radii, chamfer sizes, or slightly wrong feature positions.")

    if not h:
        h.append("Close. Tighten remaining dimensions; compare renders view-by-view "
                 "against ground truth for any small feature still missing.")
    return h


def build_report(run: RunResult, rw: RewardResult,
                 render_paths: list[str] | None = None,
                 attempt: int | None = None) -> dict:
    """Return {'markdown', 'score', 'hints', 'renders'}."""
    hs = hints(rw)
    lines = [f"### Attempt {attempt}" if attempt is not None else "### Result"]

    if not run.ok:
        lines.append(f"**BUILD FAILED** — {run.error}")
        if run.stderr.strip():
            tail = "\n".join(run.stderr.strip().splitlines()[-12:])
            lines.append("```\n" + tail + "\n```")
        lines.append("Fix the error and resubmit.")
        return {"markdown": "\n".join(lines), "score": 0.0,
                "hints": hs, "renders": render_paths or []}

    lines.append(f"**Score:** {rw.summary()}")
    lines.append(f"_(build {run.seconds:.1f}s · watertight={rw.raw.get('candidate_watertight')})_")
    lines.append("")
    lines.append("**What to fix next:**")
    lines += [f"- {x}" for x in hs]
    if render_paths:
        lines.append("")
        lines.append("**Renders (candidate vs ground truth):**")
        lines += [f"- {p}" for p in render_paths]
    return {"markdown": "\n".join(lines), "score": rw.composite,
            "hints": hs, "renders": render_paths or []}
