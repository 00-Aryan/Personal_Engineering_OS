#!/bin/bash
LATEST=$(ls -t tasks/TASK_*_RESULT.md 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "No result files found"
  exit 1
fi

echo "=== $LATEST ==="
cat "$LATEST"
echo ""
echo "=== LIVE TEST COUNT ==="
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --tb=no 2>/dev/null | tail -3
echo ""
echo "=== PENDING TASKS ==="
grep "PENDING" tasks/README.md
