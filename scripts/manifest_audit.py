#!/usr/bin/env python3
"""
manifest_audit.py — the canonical task-suite census.

Phase 0 of the breadth plan. Stops the project arguing dataset shape from stale,
mutually-contradictory counts (the plan said 21; LEADERBOARD said 9/17; the
research doc said ~17; disk has 19). This emits ONE canonical table so every
downstream dataset-shape argument stands on ground truth.

For every task it answers five questions:
  - id              the task id
  - real | synthetic  externally-authored (NIST / public STEP) vs hand-authored
  - status          solved | partial | scaffold | baseline
  - faces           B-rep face count of the ground truth (the complexity axis
                    Phase 1 is about to make less load-bearing)
  - track           spec | drawing (a MAJOR difficulty axis — never conflate
                    a 40-face spec task with a 40-face drawing task)
  - in_manifest     is the on-disk dir registered, and vice-versa (orphan check)

It also emits the FACE-COUNT HISTOGRAM — the empirical picture of where the
suite's parts actually sit, and therefore where the real-part importer (Phase 2)
needs to add HARD parts (the productive 20-100-face middle is populated by EASY
synthetic probes today, not by hard real parts — that's the true gap, sharper
than "no parts in band").

                    suite face-count distribution (schematic)
      faces:  0    10    20    50   100   150   300
              │ ████ │ ██  │ █   │     │ ██  │ █
              └ low synth ─┴ mid (mostly EASY) ┴─ NIST hard tail ┘
                                  ▲
                          Phase 2 adds HARD reals here

GROUND-TRUTH SAFETY: this reads only ground_truth/topology.json (the B-rep COUNT
signature the grader already loads, and which the manifest descriptions already
expose) plus .best_score and dir listings. It NEVER reads result.step / result.stl
/ meta.json — the answer geometry. Reading a face count is not reading the answer.

Usage:
    .venv\\Scripts\\python.exe scripts/manifest_audit.py            # print table + histogram
    .venv\\Scripts\\python.exe scripts/manifest_audit.py --md OUT.md # also write a markdown report
    .venv\\Scripts\\python.exe scripts/manifest_audit.py --json     # machine-readable
    .venv\\Scripts\\python.exe scripts/manifest_audit.py --held-out # also print the held-out recommendation

Exit codes: 0 = audit ran (even if orphans found — they print as warnings);
2 = manifest unreadable / no tasks dir.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO / "tasks"
MANIFEST = TASKS_DIR / "manifest.yaml"

# Treat >= this composite as "solved" (the harness's documented ceiling is
# ~0.97-0.99 from the sampling floor, so >=0.95 is the canonical solved line —
# see docs/known-limitations.md #7).
SOLVED_THRESHOLD = 0.95
# Below this with a recorded score = a real reconstruction attempt that stalled.
# At/above this but below solved = partial. No recorded best = scaffold.
PARTIAL_FLOOR = 0.0

# Face-count band the Phase 2 importer targets (the "productive middle").
BAND_LO, BAND_HI = 20, 100


@dataclass
class TaskRow:
    id: str
    real: bool
    status: str           # solved | partial | scaffold | baseline
    faces: int | None
    track: str            # spec | drawing
    tier: str             # easy | medium | hard (from manifest)
    best_score: float | None
    in_manifest: bool
    on_disk: bool
    in_band: bool = False
    notes: str = ""


def _read_topology_faces(task_dir: Path) -> int | None:
    """Face count from ground_truth/topology.json ONLY. Never touches geometry."""
    topo = task_dir / "ground_truth" / "topology.json"
    if not topo.exists():
        return None
    try:
        sig = json.loads(topo.read_text())
        return sig.get("faces") if isinstance(sig, dict) else None
    except Exception:
        return None


def _read_best_score(task_dir: Path) -> float | None:
    f = task_dir / ".best_score"
    if not f.exists():
        return None
    try:
        return float(f.read_text().strip())
    except Exception:
        return None


def _classify_real(task_id: str, notes: str) -> bool:
    """Externally-authored (can't be tuned easy) vs hand-authored synthetic.

    Signal, in priority order: NIST prefix (all NIST parts are real test cases);
    an explicit 'real' / 'public' / 'github' marker in the manifest notes. The
    bearing_608 case is real (public GitHub STEP) but has no nist_ prefix, so the
    notes marker catches it.
    """
    n = (notes or "").lower()
    if task_id.startswith("nist_"):
        return True
    return ("real " in n or "real externally" in n or "public github" in n
            or "real-by-construction" in n or "externally-authored" in n
            or "real nist" in n)


def _classify_status(best: float | None) -> str:
    if best is None:
        return "scaffold"           # registered + has GT, but never graded to a kept best
    if best >= SOLVED_THRESHOLD:
        return "solved"
    if best > PARTIAL_FLOOR:
        return "partial"            # a real attempt that stalled (topology-capped or unsolved)
    return "baseline"               # graded but ~0 (placeholder/bbox probe)


def audit() -> tuple[list[TaskRow], list[str]]:
    """Return (rows, warnings). Warnings flag manifest/disk mismatches."""
    if not MANIFEST.exists():
        print(f"ERROR: no manifest at {MANIFEST}", file=sys.stderr)
        sys.exit(2)
    if not TASKS_DIR.is_dir():
        print(f"ERROR: no tasks dir at {TASKS_DIR}", file=sys.stderr)
        sys.exit(2)

    manifest = yaml.safe_load(MANIFEST.read_text())
    manifest_tasks = {t["id"]: t for t in manifest.get("tasks", [])}

    # Dirs on disk that contain a ground_truth/ (a real task dir, not a stray file).
    disk_dirs = {p.name for p in TASKS_DIR.iterdir()
                 if p.is_dir() and (p / "ground_truth").exists()}
    # Dirs on disk WITHOUT ground_truth (potential strays / empty orphans).
    stray_dirs = {p.name for p in TASKS_DIR.iterdir()
                  if p.is_dir() and not (p / "ground_truth").exists()}

    warnings: list[str] = []
    all_ids = set(manifest_tasks) | disk_dirs

    rows: list[TaskRow] = []
    for tid in sorted(all_ids):
        m = manifest_tasks.get(tid)
        in_manifest = m is not None
        on_disk = tid in disk_dirs
        task_dir = TASKS_DIR / tid

        if in_manifest and not on_disk:
            warnings.append(f"ORPHAN(manifest): '{tid}' is registered but has no "
                            f"ground_truth/ on disk")
        if on_disk and not in_manifest:
            warnings.append(f"ORPHAN(disk): '{tid}' has a ground_truth/ dir but is "
                            f"NOT in manifest.yaml")

        notes = (m.get("notes") if m else "") or ""
        faces = _read_topology_faces(task_dir) if on_disk else None
        best = _read_best_score(task_dir) if on_disk else None
        track = (m.get("default_track") if m else None) or "spec"
        tier = (m.get("tier") if m else None) or "?"

        rows.append(TaskRow(
            id=tid,
            real=_classify_real(tid, notes),
            status=_classify_status(best),
            faces=faces,
            track=track,
            tier=tier,
            best_score=best,
            in_manifest=in_manifest,
            on_disk=on_disk,
            in_band=(faces is not None and BAND_LO <= faces <= BAND_HI),
        ))

    for s in sorted(stray_dirs):
        warnings.append(f"STRAY(dir): tasks/{s}/ exists with no ground_truth/ "
                        f"(empty/scaffold dir — confirm it's intentional)")

    return rows, warnings


# ── face-count histogram ──────────────────────────────────────────────────────

# Bins chosen to make the bimodal shape legible: dense low bins (where the
# synthetic easies cluster), the 20-100 target band as ONE bin you can read at a
# glance, then the NIST hard tail.
_BINS = [(0, 9), (10, 19), (20, 49), (50, 99), (100, 149), (150, 199), (200, 999)]


def _bin_label(lo: int, hi: int) -> str:
    return f"{lo:>3}-{hi:<3}" if hi < 999 else f"{lo:>3}+   "


def face_histogram(rows: list[TaskRow]) -> list[tuple[str, int, int, int]]:
    """Return [(label, total, real_count, in_band_flag)] per bin."""
    out = []
    for lo, hi in _BINS:
        in_bin = [r for r in rows if r.faces is not None and lo <= r.faces <= hi]
        reals = sum(1 for r in in_bin if r.real)
        out.append((_bin_label(lo, hi), len(in_bin), reals, 1 if (lo >= BAND_LO and hi <= BAND_HI) else 0))
    return out


def recommend_held_out(rows: list[TaskRow]) -> list[str]:
    """Held-out policy: reserve the REAL parts that already sit in or near the
    target band and are NOT solved-trivially — they're the honest evaluation set
    (can't be tuned, genuinely hard). Quarantine these BEFORE any reward tuning or
    grid run touches them (the Codex F14 lesson: a held-out part that already
    shaped a reward change isn't a credible held-out part).

    Today the real, non-trivial set is the NIST hard tail. As Phase 2 imports real
    mid-band parts, the held-out set should be re-struck from THOSE (stratified by
    face-band), reserving >=10. This function reports the current best held-out
    candidates from the existing suite as a starting point."""
    candidates = [r for r in rows
                  if r.real and r.status in ("partial", "scaffold")]
    # Prefer ones in/above the band (the hard ones), sorted by faces.
    candidates.sort(key=lambda r: (r.faces is None, r.faces or 0))
    return [r.id for r in candidates]


# ── rendering ─────────────────────────────────────────────────────────────────

def render_table(rows: list[TaskRow]) -> str:
    hdr = (f"{'id':<18} {'real?':<5} {'status':<9} {'faces':>5} "
           f"{'track':<8} {'tier':<7} {'best':>7} {'band?':<5}")
    sep = "-" * len(hdr)
    lines = [hdr, sep]
    for r in sorted(rows, key=lambda x: (x.faces is None, x.faces or 0)):
        best = f"{r.best_score:.4f}" if r.best_score is not None else "-"
        faces = str(r.faces) if r.faces is not None else "?"
        flags = ""
        if not r.in_manifest:
            flags = " <DISK-ONLY"
        elif not r.on_disk:
            flags = " <MANIFEST-ONLY"
        lines.append(
            f"{r.id:<18} {('Y' if r.real else 'N'):<5} {r.status:<9} "
            f"{faces:>5} {r.track:<8} {r.tier:<7} {best:>7} "
            f"{('IN' if r.in_band else '--'):<5}{flags}")
    return "\n".join(lines)


def render_histogram(rows: list[TaskRow]) -> str:
    hist = face_histogram(rows)
    lines = ["FACE-COUNT HISTOGRAM (bar = total; (R) = how many are REAL):", ""]
    maxn = max((n for _, n, _, _ in hist), default=1) or 1
    for label, n, reals, is_band in hist:
        bar = "#" * int(round(20 * n / maxn))
        band = "  <- TARGET BAND" if is_band else ""
        lines.append(f"  {label} | {bar:<20} {n:>2}  (R:{reals}){band}")
    return "\n".join(lines)


def render_summary(rows: list[TaskRow]) -> str:
    total = len(rows)
    real = sum(1 for r in rows if r.real)
    synth = total - real
    by_status = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    in_band = [r for r in rows if r.in_band]
    band_real_hard = [r for r in in_band if r.real and r.status != "solved"]
    by_track = {}
    for r in rows:
        by_track[r.track] = by_track.get(r.track, 0) + 1

    lines = [
        f"CANONICAL COUNT: {total} tasks "
        f"({real} real, {synth} synthetic)",
        f"  by status: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())),
        f"  by track:  " + ", ".join(f"{k}={v}" for k, v in sorted(by_track.items())),
        f"  in 20-100 face band: {len(in_band)} total, of which "
        f"{sum(1 for r in in_band if r.real)} real, "
        f"{len(band_real_hard)} real-AND-not-solved",
        "",
        "THE REAL GAP (sharper than 'no parts in band'): the 20-100 band is "
        f"populated by {len(in_band) - len(band_real_hard)} EASY/solved parts; only "
        f"{len(band_real_hard)} real-and-hard part(s) sit there. Phase 2 fills the "
        "HARD-REAL slot, not an empty band.",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Canonical task-suite census.")
    ap.add_argument("--md", help="write a markdown report to this path")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--held-out", action="store_true",
                    help="print the held-out recommendation")
    args = ap.parse_args()

    rows, warnings = audit()

    if args.json:
        out = {
            "count": len(rows),
            "real": sum(1 for r in rows if r.real),
            "synthetic": sum(1 for r in rows if not r.real),
            "tasks": [asdict(r) for r in rows],
            "histogram": [
                {"band": lbl, "total": n, "real": reals, "is_target_band": bool(b)}
                for lbl, n, reals, b in face_histogram(rows)
            ],
            "held_out_recommendation": recommend_held_out(rows),
            "warnings": warnings,
        }
        print(json.dumps(out, indent=2))
        return

    table = render_table(rows)
    hist = render_histogram(rows)
    summary = render_summary(rows)

    print("=" * 72)
    print("CANONICAL TASK MANIFEST AUDIT")
    print("=" * 72)
    print(summary)
    print()
    print(table)
    print()
    print(hist)
    print()
    if warnings:
        print("WARNINGS (manifest/disk reconciliation):")
        for w in warnings:
            print(f"  ! {w}")
    else:
        print("RECONCILIATION: clean - every manifest entry has a dir and vice-versa.")
    print()

    if args.held_out:
        ho = recommend_held_out(rows)
        print("HELD-OUT RECOMMENDATION (real + not-solved; quarantine before tuning):")
        for tid in ho:
            r = next(x for x in rows if x.id == tid)
            print(f"  - {tid} ({r.faces} faces, {r.status}, {r.track}-track)")
        print(f"\n  NOTE: this is {len(ho)} from the EXISTING suite. The plan targets "
              ">=10 held-out\n  stratified by face-band — re-strike from Phase 2's "
              "imported real parts\n  once they land (Codex F14: quarantine at import "
              "time, before any solver/tuning).")
        print()

    if args.md:
        md_path = Path(args.md)
        md = (
            "# Canonical Task Manifest Audit\n\n"
            f"_Generated by `scripts/manifest_audit.py`._\n\n"
            "## Summary\n\n```\n" + summary + "\n```\n\n"
            "## Canonical table\n\n```\n" + table + "\n```\n\n"
            "## Face-count histogram\n\n```\n" + hist + "\n```\n\n"
            "## Reconciliation\n\n"
            + ("All clean — manifest and disk agree.\n"
               if not warnings else
               "".join(f"- {w}\n" for w in warnings))
            + "\n## Held-out recommendation\n\n```\n"
            + "\n".join(recommend_held_out(rows)) + "\n```\n"
        )
        md_path.write_text(md, encoding="utf-8")
        print(f"[markdown report written to {md_path}]")


if __name__ == "__main__":
    main()
