#!/bin/bash
LOOP=1
if [[ "$1" == "--loop" && -n "$2" ]]; then
  LOOP=$2
fi

# Check provider status
if [ -f ".projectos_state/provider_status.json" ]; then
  echo "Providers available for this run:"
  python3 -c "
import json, sys
try:
    data = json.load(open('.projectos_state/provider_status.json'))
    for k, v in data.items():
        if isinstance(v, dict) and 'available' in v:
            status = 'available' if v.get('available') else 'unavailable'
            err = v.get('error', '')
            print(f'  {k}: {status}' + (f' - {err}' if err else ''))
except Exception as ex:
    print(f'  error reading provider status: {ex}')
"
else
  python3 scripts/setup_providers.py --no-prompt 2>/dev/null || true
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

  if [ $i -lt $LOOP ]; then
    sleep 5
  fi
done

echo ""
echo "━━━ DONE. Share results: bash scripts/share_results.sh ━━━"
