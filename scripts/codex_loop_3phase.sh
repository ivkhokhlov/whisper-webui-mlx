#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/codex_loop_3phase.sh 50
#
# Environment variables:
#   SANDBOX=workspace-write|danger-full-access   (default: workspace-write)
#   APPROVALS=never|on-request|...              (default: never)

N="${1:-50}"
SANDBOX="${SANDBOX:-danger-full-access}"
# APPROVALS="${APPROVALS:-never}"

mkdir -p .agent/logs

for ((i=1; i<=N; i++)); do
  if [[ -f .agent/STOP || -f .agent/DONE ]]; then
    echo "STOP or DONE detected. Exiting."
    break
  fi

  export CODEX_ITERATION="$i"

  echo "=== CYCLE $i / $N: PLANNER ==="
  codex-proxy --search exec --cd . --sandbox "$SANDBOX" --output-last-message ".agent/last_planner.txt"     - < .agent/planner.md     > ".agent/logs/planner_${i}.out" 2> ".agent/logs/planner_${i}.err" || true

  if [[ -f .agent/STOP || -f .agent/DONE ]]; then
    echo "STOP or DONE detected after planner. Exiting."
    break
  fi

  echo "=== CYCLE $i / $N: WORKER ==="
  codex-proxy exec --cd . --sandbox "$SANDBOX" --output-last-message ".agent/last_worker.txt"     - < .agent/worker.md     > ".agent/logs/worker_${i}.out" 2> ".agent/logs/worker_${i}.err" || true

  echo "=== CYCLE $i / $N: JUDGE ==="
  codex-proxy exec --cd . --sandbox "$SANDBOX" --output-last-message ".agent/last_judge.txt"     - < .agent/judge.md     > ".agent/logs/judge_${i}.out" 2> ".agent/logs/judge_${i}.err" || true

  echo "--- tail progress ---"
  tail -n 25 .agent/progress.md || true
  echo
done
