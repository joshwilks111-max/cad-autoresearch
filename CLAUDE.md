# CLAUDE.md — repo conventions for Claude Code

This repo is a CAD autoresearch harness. If you are a **worker agent**, your manual
is `program.md` — read it and follow it. This file is the project map and the rules
that apply to anyone (human or agent) operating in the repo.

## What this is
A Karpathy-style autoresearch loop for AI-to-CAD. Agents write `build123d` programs
that reconstruct a target part; a deterministic six-layer reward grades each against
a hidden ground-truth STEP; agents iterate on the score + feedback. An orchestrator
fans out a grid of workers; each worker may spawn subagents.

## Project map
```
program.md            the worker prompt (humans iterate this)
config.yaml           grid + worker + watcher + reward defaults
orchestrator.py       spawns the worker grid (tmux | subprocess); aggregates best
watcher.py            keeps the grid alive, live leaderboard, optional meta agent
run_inner_loop.py     ONE worker: propose -> build -> grade -> render -> keep/discard
harness/
  geometry.py         volume, bbox, Chamfer, pose-invariant volumetric IoU, topology
  reward.py           six-layer composite score (RewardConfig, RewardResult)
  runner.py           sandboxed execution of a candidate -> STEP/STL/topology
  render.py           headless multi-view PNGs (matplotlib Agg)
  feedback.py         compact "what to fix next" report
loop/
  ledger.py           append-only jsonl experiment log + keep/discard rule
  policies.py         MockProposer (offline) + ClaudeCodeProposer (real CLI)
tasks/
  manifest.yaml       task registry (spec/drawing tracks, difficulty tiers)
  sample_bracket/     toy task with make_ground_truth.py (+ spec.md, drawing notes)
prompts/              worker_system, vision_subagent, debugger_subagent, meta_agent
scripts/              setup.sh, launch.sh, DATASETS.md
tests/test_reward.py  validates the grader + runner
runs/                 ALL runtime output (gitignored)
```

## Deeper docs (read on demand)
`docs/` has the architecture + hard-won knowledge: `ARCHITECTURE.md` (reward layers, loop,
task model), `reward-design.md` (why), `known-limitations.md` (the landmine map — topology
ceiling, OCC traps, hole-detection limits, the DEAD config.yaml reward block), `tools-reference.md`
(the 8 tools), `research-and-deferred.md` (solved / tried-rejected / roadmap). Read
`known-limitations.md` before concluding a low score means a bad reconstruction.

## The candidate contract
A candidate is a Python program that assigns the final solid to a module-level
variable **`result`** (build123d BuildPart/Part/Solid, or a CadQuery Workplane).
The sandbox appends the export/grade epilogue — candidates must NOT export or grade
themselves.

## How to run
- Offline smoke test (no API):
  `python run_inner_loop.py --task sample_bracket --proposer mock --budget 5`
- Single real worker:
  `python run_inner_loop.py --task sample_bracket --proposer claude --model opus --budget 30`
- Full grid:
  `python orchestrator.py --proposer claude --workers 4`  then  `python watcher.py`
- Tests: `pytest -q`  (build the sample GT first via setup.sh)

**Billing plane.** `--proposer claude` drives the **`claude` CLI in `-p` (print) mode**, which
bills your **subscription via OAuth** — there is no `anthropic.Anthropic()` client in this repo,
so the orchestrator is NOT metered-API work. The one caveat: `claude -p` *prefers*
`ANTHROPIC_API_KEY` if it's set in the env, which would silently bill the API instead. The loop
**scrubs that var in-process** at the two `claude`-spawn seams (`loop/policies.py`, `watcher.py`)
and the launcher prints which plane is active. Rule: keep `ANTHROPIC_API_KEY` unset; don't set it
to "enable" runs — it does the opposite of what you want.

## Guardrails (do not violate)
- **Never read anything under any `ground_truth/` directory.** It is the hidden
  answer key; the harness loads it, agents must not.
- Workers run **headless** and each in an **isolated run directory**. Do not point
  two workers at the same workspace — concurrent writers corrupt each other.
- Agents do not edit `harness/`, `reward.py`, the orchestrator, or task ground
  truth. The meta agent (outer loop) may edit ONLY `program.md`.
- Builds run in a subprocess with a timeout; a failure is graded 0, not crashed.

## Branching & shipping
- **New substantive work starts on a `feat/`-prefixed branch off `main`** — not on
  `main` directly. This is what lets `/ship` work: it lands a feature branch into the
  base via a reviewed PR. `/ship` ABORTS on the base branch (nothing to land).
- Trivial one-liners (typo, comment, version bump) may go straight to `main`.
- `main` is the base/default branch. Don't rewrite its pushed history to fake a PR.
- The 8 grading/authoring tools + their `/review` fixes (commits `ae0530a`..`33d00c6`)
  landed directly on `main` before this convention existed — that was the old pattern;
  going forward, branch first.

## Skill routing (gstack)
When a request matches a gstack skill, invoke it via the Skill tool. When in doubt, invoke it.
- Bugs / errors / "why does X fail" → `/investigate`
- Code review / diff check before landing → `/review`
- QA / testing site behavior → `/qa` or `/qa-only`
- Ship / deploy / create a PR → `/ship` (from a `feat/` branch, never the base)
- Full review gauntlet on a plan → `/autoplan`
- Strategy/scope → `/plan-ceo-review`; architecture → `/plan-eng-review`
- Save / resume progress → `/context-save` / `/context-restore`
- Web browsing → `/browse` (never the chrome MCP tools directly)

## gstack best practices (always-on)
- **Boil the Lake:** AI makes completeness cheap — do the whole thing (tests, edge
  cases, error paths), not the demo path. Flag true oceans (rewrites), don't punt lakes.
- **Verify before asserting:** this stack moves weekly. Confirm flags/APIs/schemas
  against source-on-disk, recent docs, or a direct test before acting. Say so if a claim
  is from memory and unverified. Running code wins over training memory.
- **Search before building:** reuse Layer-1 (tried-and-true) and scrutinise Layer-2
  (new/popular) before reinventing; prize first-principles when they contradict dogma.
- **Decisions are the user's:** surface close calls via AskUserQuestion (one clear
  recommendation + honest tradeoffs); don't auto-decide architecture, scope, or
  destructive actions.

## Token discipline (matches how this is meant to be run)
- Use **Opus** for planning, decomposition, and the hard drawing-track reading;
  use **Sonnet** to grind many execution attempts where the spec is clear. Set per
  worker via `--model`, or split the grid (some opus workers, some sonnet).
- Clear context between phases; keep the per-turn feedback report terse (it's
  designed to be).

## Billing caveat (read before an overnight grid)
From **2026-06-15**, headless `claude -p` / Agent SDK usage on subscription plans
draws from a separate monthly Agent SDK credit allotment. A large overnight grid is
many headless turns — check your plan's Agent SDK limits (docs.claude.com) before
launching hundreds of worker-turns, or you may stall mid-run.
