# verify.ps1 — one command for a skeptic (Windows): re-grade the committed trial STEPs
# from disk and print the headline. Proves the result reproduces without trusting our
# writeup.
#
# Setup (once): build123d 0.10 needs Python < 3.14. The fast path:
#   uv venv --python 3.13 ; uv pip install -r requirements.txt
# then run this from the repo root:  .\timetrial\verify.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$PY = ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { $PY = "python" }

Write-Output "=== referee self-test (GT STEP must score ~1.0) ==="
& $PY timetrial\grade_step.py --task trial_lbracket `
    --step tasks\trial_lbracket\ground_truth\result.step

Write-Output ""
Write-Output "=== re-grade committed trial submissions + honesty checks ==="
if ((Test-Path timetrial\artifacts) -and (Get-ChildItem timetrial\artifacts\*.step -ErrorAction SilentlyContinue)) {
    & $PY timetrial\trial.py verify --bar 0.95
    Write-Output ""
    & $PY timetrial\trial.py aggregate
} else {
    Write-Output "(no committed submissions in timetrial\artifacts\ yet - run the trial per PROTOCOL.md,"
    Write-Output " then re-run this script to reproduce the headline.)"
}
