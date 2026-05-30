# Grid Run Leaderboard — first run of the completed harness (2026-05-30)

First real grid run across all tasks. On-subscription (mock proposer + grading only;
no API/claude proposer, no orchestrator/watcher). 6/12 tasks solved >= 0.95
(mean composite of solved = 0.9967). Reproducible from each task's
`tasks/<id>/best_candidate.py`.

| Rank | Task | Tier | Track | Composite | GT faces | iou_res | grade s |
|---|---|---|---|---|---|---|---|
| 1 | rib_probe | easy | spec | 0.999 | 66 | 64 | 8.3 |
| 2 | perf_plate | easy | spec | 0.998 | 21 | 48 | 19.6 |
| 3 | sample_bracket | easy | spec | 0.997 | 15 | 64 | 36.8 |
| 4 | twin_bodies | easy | spec | 0.997 | 12 | 64 | 5.3 |
| 5 | motor_mount | easy | spec | 0.996 | 15 | 64 | 38.2 |
| 6 | thinwall_box | easy | spec | 0.993 | 11 | 64 | 10.0 |
| 7 | nist_ftc_11* | easy | drawing | 0.524 | 6 | 51 | 22.6 |
| 8 | nist_ftc_09* | hard | drawing | 0.284 | 163 | 64 | 26.8 |
| 9 | nist_ftc_07* | hard | drawing | 0.244 | 306 | 64 | 153.0 |
| 10 | nist_stc_06* | hard | drawing | 0.243 | 144 | 64 | 67.3 |
| 11 | nist_ctc_05* | hard | drawing | 0.193 | 156 | 64 | 45.3 |
| 12 | nist_ctc_03* | medium | drawing | 0.167 | 120 | 64 | 32.1 |

`*` = bbox-baseline only (no committable reconstruction yet; these are hard
drawing-track parts). STC-06 has a real partial reconstruction at 0.655 (git history,
commit ec5f0f7) — the 0.243 here is its bbox baseline since its candidate.py was not
re-derived for this run.

## Mock inner loop (sample_bracket, --proposer mock --budget 8)
Demonstrates the autoresearch loop ITERATING (propose -> grade -> keep/discard):
```
attempt 001  composite=0.061   (degenerate)
attempt 002  composite=0.725   (right plate, features missing)
attempt 003  composite=0.743
attempt 004  composite=0.997   TARGET HIT
```

## Notes
- Solved spec-track parts cluster 0.993-0.999, gated only by the chamfer sampling
  floor (every other layer = 1.000). The reward is well-calibrated.
- Hard real parts score 0.167-0.524 for a featureless box — correctly far-from-done.
  The ordering tracks "how box-like is the part" (ftc_11 near-box highest, ctc_03
  deep-pocketed lowest).
- Adaptive IoU resolution is visible: small parts use res 24-51, large parts cap at
  64. Cost scales with part size: ftc_07 (306 faces) was slowest at 153s.
- Scaling to a LARGE autonomous grid (many proposing attempts) needs the Agent-SDK
  credit (from 2026-06-15) or an API key — proposing can't stay on one interactive
  session. This run is the mechanical grid at full breadth on subscription.
