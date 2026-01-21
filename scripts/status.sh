#!/usr/bin/env bash
set -euo pipefail

echo "=== Queue (top) ==="
sed -n '1,120p' .agent/queue.md 2>/dev/null || echo "(missing .agent/queue.md)"

echo
echo "=== Progress (tail) ==="
tail -n 40 .agent/progress.md 2>/dev/null || echo "(missing .agent/progress.md)"

echo
echo "=== Last judge ==="
tail -n 40 .agent/last_judge.txt 2>/dev/null || echo "(missing .agent/last_judge.txt)"
