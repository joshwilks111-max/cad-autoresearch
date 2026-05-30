#!/usr/bin/env bash
# Launch a real grid + watcher in one go. Args override config.yaml.
# Usage: scripts/launch.sh [WORKERS] [TASK] [MODEL]
set -euo pipefail
cd "$(dirname "$0")/.."
WORKERS="${1:-4}"; TASK="${2:-sample_bracket}"; MODEL="${3:-opus}"

python orchestrator.py --proposer claude --workers "$WORKERS" --tasks "$TASK" --model "$MODEL"
echo "grid launched. attaching watcher (Ctrl-C to stop watching; workers keep running)..."
python watcher.py
