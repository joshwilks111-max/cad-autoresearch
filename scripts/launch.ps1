# launch.ps1 — Windows mirror of scripts/launch.sh. Launch a real grid + watcher in
# one go; args override config.yaml.
#
#   Usage:  .\scripts\launch.ps1 [WORKERS] [TASK] [MODEL]
#   e.g.    .\scripts\launch.ps1 1 sample_bracket opus
#
# Two Windows-specific differences from launch.sh:
#   1. --backend subprocess  — config.yaml defaults to `tmux`, which is absent on
#      native Windows (orchestrator.py exits "tmux not found"). subprocess works
#      everywhere and is the orchestrator's own argparse default.
#   2. ANTHROPIC_API_KEY is unset for THIS launcher's process tree, so the grid bills
#      your SUBSCRIPTION via `claude -p` OAuth. (The loop ALSO scrubs the key in-process
#      at each `claude` spawn — see loop/billing.py — so this is belt-and-suspenders +
#      makes the banner read cleanly. It does NOT touch your persistent User-scope var.)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$PY = ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { $PY = "python" }

$WORKERS = if ($args.Count -ge 1) { $args[0] } else { "4" }
$TASK    = if ($args.Count -ge 2) { $args[1] } else { "sample_bracket" }
$MODEL   = if ($args.Count -ge 3) { $args[2] } else { "opus" }

# keep this launch on the subscription (does not persist; process-scope only)
$env:ANTHROPIC_API_KEY = $null

# Billing caveat (read before an overnight grid): from 2026-06-15, headless `claude -p`
# / Agent SDK usage on subscription plans draws from a separate monthly Agent SDK credit
# allotment — check your plan's limits before launching hundreds of worker-turns.

& $PY orchestrator.py --proposer claude --backend subprocess `
    --workers $WORKERS --tasks $TASK --model $MODEL

Write-Output "grid launched (subprocess backend). attaching watcher (Ctrl-C to stop watching; workers keep running)..."
& $PY watcher.py
