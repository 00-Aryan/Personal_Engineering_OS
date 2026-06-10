#!/bin/bash

# Move any result files dropped in root into tasks/ first
for f in TASK_*_RESULT.md; do
  [ -f "$f" ] && mv "$f" "tasks/$f" && echo "⚠️  Moved $f → tasks/$f"
done

LATEST=$(ls -t tasks/TASK_*_RESULT.md 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "No result files found"
  exit 1
fi

echo "=== $LATEST ==="
cat "$LATEST"
echo ""
echo "=== LIVE TEST COUNT ==="
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --tb=no --timeout=30 2>/dev/null | tail -3
echo ""
echo "=== PENDING TASKS ==="
grep "PENDING" tasks/README.md
