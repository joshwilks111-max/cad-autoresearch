#!/usr/bin/env bash
# One-time setup: install deps and build the sample ground truth.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== installing python deps =="
# On Debian/Ubuntu base images you may need --break-system-packages.
pip install -r requirements.txt || pip install --break-system-packages -r requirements.txt

echo "== building sample ground truth =="
python tasks/sample_bracket/make_ground_truth.py

echo "== smoke test: offline mock loop (no API) =="
python run_inner_loop.py --task sample_bracket --proposer mock --budget 5 --worker w0

echo
echo "Setup OK. Next:"
echo "  • offline test passed above (mock proposer, no API)."
echo "  • real grid:  python orchestrator.py --proposer claude --workers 4"
echo "  • watch    :  python watcher.py --session cadar"
