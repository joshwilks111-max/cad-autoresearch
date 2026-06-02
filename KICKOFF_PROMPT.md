# Kickoff prompt — interactive loop on your subscription

Open Claude Code **in the repo root** on your Pro/Max plan and paste the block
below as your first message. It runs the autoresearch loop interactively (you in
the loop, watching), with no headless `claude -p`, no orchestrator, and no API
key — so it stays on your subscription.

**Before you paste:** confirm you're on plan billing, not API. In Claude Code run
`/status`; if it shows an API/Console account, run `claude logout`, then
`claude login` with only your plan credentials, and make sure `ANTHROPIC_API_KEY`
is **not** set in your shell.

---

```
You're working in a CAD autoresearch repo. Before doing anything else, read
program.md (your operating manual) and CLAUDE.md (repo conventions) in full —
they define the loop, the candidate contract, the scoring, and the guardrails.
Follow them exactly.

We are running this loop INTERACTIVELY, with me watching — not headless. You are
the proposer and you grade your own candidates with the harness. In THIS session,
don't launch orchestrator.py, watcher.py, or `run_inner_loop.py --proposer claude`
— not because they bill the API (they don't; they shell out to `claude -p`, which
bills my subscription via OAuth), but because they're the *unattended grid* path
and we're doing the *interactive watching* path here. The only model doing work in
this session is you. One billing rule applies to BOTH paths: keep `ANTHROPIC_API_KEY`
unset — `claude -p` prefers it when present, which is the one way to accidentally
hit the metered API.

SETUP (do once, show me the output):
1. If tasks/sample_bracket/ground_truth/result.stl is missing, run:
   python tasks/sample_bracket/make_ground_truth.py
2. Sanity-check the harness with the offline mock loop (no model calls):
   python run_inner_loop.py --task sample_bracket --proposer mock --budget 5
   Confirm it climbs and hits target.

THE TASK: reconstruct sample_bracket on the SPEC track. Read
tasks/sample_bracket/spec.md — that is your only input. Do NOT read anything under
tasks/sample_bracket/ground_truth/; it is the hidden answer key.

THE LOOP (repeat):
1. Write your best build123d program to ./candidate.py, defining a module-level
   variable `result` (see program.md's candidate contract and cheat-sheet).
2. Grade it:
   python grade_one.py --task sample_bracket --candidate candidate.py
3. Read the printed score breakdown and runs/manual/feedback.md, and VIEW the four
   render PNGs in runs/manual/renders/ — compare your part to ground truth view by
   view. Numbers tell you THAT something's wrong; the images tell you WHAT.
4. Make ONE clear improvement targeting the lowest sub-score, in this priority:
   body -> bbox -> volume -> iou -> topology -> chamfer. Keep what already scored
   well; don't regress.
5. Show me the one-line score each turn so I can follow along.

Keep iterating on your own while the score improves. Stop and check in with me if
(a) you reach composite >= 0.95, or (b) the score plateaus for 3 turns. When you
hit target, show me the final candidate.py, the final score, and where the STEP
file is.

Begin by reading program.md and CLAUDE.md, then run setup, then take your first
attempt.
```

---

## What to expect
- On the spec track this part is easy; a competent first attempt often lands
  ~0.86 (right plate, features missing) and reaches ≥0.95 within a few turns once
  the four holes and the central slot are in.
- Each grade prints a score line like
  `composite=0.862 [body=1 vol=0.842 bbox=1.000 topo=0.400 iou=0.961 cham=0.975]`
  plus targeted hints and refreshed renders under `runs/manual/`.
- Treat **composite ≥ ~0.95 as "solved"** — identical geometry caps near 0.97–0.99
  because of a sampling-spacing floor, not 1.0.

## Next steps once this works
- Swap in a real part: add a task under `tasks/<id>/` (NIST PMI, Model Mania — see
  `scripts/DATASETS.md`) and point the loop at it.
- Try the **drawing track**: drop a `drawing.png` in the task folder and change the
  prompt's input line to the drawing instead of `spec.md`. That's the hard,
  vision-bound half — where a dedicated reading pass (prompts/vision_subagent.md)
  earns its keep.
- When you want scale/overnight runs, move to the grid (`orchestrator.py`) — it runs
  on your subscription too (it drives `claude -p`, not the API). From 2026-06-15,
  headless `claude -p` draws from a separate monthly Agent SDK credit allotment, so
  check your plan's limits before a hundreds-of-turns overnight grid.
