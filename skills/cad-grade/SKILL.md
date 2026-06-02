---
name: cad-grade
description: Score a CAD part (a STEP file, or a build123d candidate) against a reference, deterministically, through the same multi-layer geometric referee the autoresearch loop uses. Use to certify a reconstruction's fidelity, compare a human STEP to an AI one on equal footing, or grade a finished part against a registered task's ground truth or a bring-your-own reference STEP. Triggers on "grade this STEP", "score this part against the reference", "how close is this to the target", "is this reconstruction correct", or running the time-trial referee. Returns a composite plus per-layer scores (body/bbox/volume/IoU/topology/chamfer) and actionable gaps. Do not use to model a part (that's cad-reconstruct) or to read a drawing (that's drawing-read).
---

# CAD grade

Deterministically score a part against a reference — the **model → score** step of
the AI-to-CAD pipeline (`drawing-read → cad-reconstruct → cad-grade`, see
`docs/skills.md`). This pack is the impartial referee: it points at the harness's
existing grading entrypoints; it does **not** reimplement or edit the reward.

## What it scores
A composite in [0,1] plus independent per-layer scores:
- **body** — is it a valid watertight solid at all (a degenerate/empty build is 0).
- **bbox** — overall envelope (sorted extents).
- **volume** — total volume (catches polarity errors: a feature that should cut but
  added comes back over).
- **iou** — gross shape/proportion (pose-invariant; cylindrical path for round parts).
- **topology** — B-rep face/edge/vertex match (every missing fillet/chamfer/hole).
- **chamfer** — exact radii and feature positions (a surface-distance term).

Treat composite ≥ ~0.95 as "solved" — identical geometry caps near 0.97–0.99 from a
sampling-spacing floor, not 1.0. High-face parts can be topology-capped well below
that even with perfect geometry; read `docs/known-limitations.md` before calling a
low score a bad reconstruction.

## How to run
- Grade a finished **STEP** against a registered task's hidden ground truth:
  ```
  python timetrial/grade_step.py --task <task_id> --step path/to/part.step --json
  ```
- Bring-your-own reference (grade one STEP against another STEP):
  ```
  python timetrial/grade_step.py --ref reference.step --step mine.step --json
  ```
- Grade a **build123d candidate** (a `candidate.py` defining `result`) in the loop:
  ```
  python grade_one.py --task <task_id> --candidate candidate.py
  ```

## The commensurability rule (why this pack exists)
A STEP and a build123d candidate must be graded through the **identical** path or
the comparison is rigged. `grade_step.py` imports the STEP, tessellates at a pinned
tolerance, and computes a **B-rep topology signature** (`topology_signature_from_solid`)
— NOT the mesh proxy. If you instead load a STEP to a mesh and grade with
`candidate_sig=None`, topology resolves to the mesh-proxy schema
(`{components, euler, watertight}`); compared against a GT B-rep signature
(`{faces, edges, ...}`) that schema clash returns a hardcoded NEUTRAL 0.5, which
silently favours the side that got a real B-rep score. Always grade STEPs through
`grade_step.py`, never an ad-hoc mesh path.

## Guardrails
- This pack is **grader-side**: its output reveals reference geometry, so it is for
  certification/verification, never fed into a worker's drawing-track spec.
- It is **pure** — `grade_step.py` prints only; it never writes `best_candidate.py`
  / `.best_score`, never touches the shared `runs/manual` workspace, and re-running
  gives identical output (safe to run repeatedly; won't dirty `git status`).
- Do NOT edit `harness/reward.py` to "improve" a score here — this pack consumes the
  referee, it does not change it. Reward changes are a separate, guarded task.
- Exit codes: 0 graded OK; 2 bad usage; 3 STEP import failed; 4 no valid solid /
  no B-rep topology (non-commensurable — refused rather than scored misleadingly).
