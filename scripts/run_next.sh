#!/bin/bash
# Run next pending task unattended
# Usage: bash scripts/run_next.sh
# Usage (loop N tasks): bash scripts/run_next.sh --loop 3

LOOP=1
if [[ "$1" == "--loop" && -n "$2" ]]; then
  LOOP=$2
fi

for i in $(seq 1 $LOOP); do
  echo "━━━ Running task $i of $LOOP ━━━"
  
  NEXT=$(grep "PENDING" tasks/README.md | head -1)
  if [ -z "$NEXT" ]; then
    echo "No PENDING tasks found. All done."
    exit 0
  fi
  
  echo "Next: $NEXT"
  agy --dangerously-skip-permissions -p "/run-task"
  
  echo "━━━ Task $i complete. Running audit... ━━━"
  agy --dangerously-skip-permissions -p "/audit"
  
  # Brief pause between tasks
  if [ $i -lt $LOOP ]; then
    sleep 5
  fi
done

echo ""
echo "━━━ DONE. Share results with Claude: ━━━"
bash scripts/share_results.sh
