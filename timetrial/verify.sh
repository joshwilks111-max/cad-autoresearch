#!/usr/bin/env bash
# verify.sh — one command for a skeptic: re-grade the committed trial STEPs from disk
# and print the headline. Proves the result reproduces without trusting our writeup.
#
# Setup (once): build123d 0.10 needs Python < 3.14. The fast path:
#   uv venv --python 3.13 && uv pip install -r requirements.txt
# then run this from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=".venv/Scripts/python.exe"   # Windows venv layout
[ -x "$PY" ] || PY="python3"

echo "=== referee self-test (GT STEP must score ~1.0) ==="
"$PY" timetrial/grade_step.py --task trial_lbracket \
    --step tasks/trial_lbracket/ground_truth/result.step

echo ""
echo "=== re-grade committed trial submissions + honesty checks ==="
if [ -d timetrial/artifacts ] && ls timetrial/artifacts/*.step >/dev/null 2>&1; then
  "$PY" timetrial/trial.py verify --bar 0.95
  echo ""
  "$PY" timetrial/trial.py aggregate
else
  echo "(no committed submissions in timetrial/artifacts/ yet — run the trial per PROTOCOL.md,"
  echo " then re-run this script to reproduce the headline.)"
fi
