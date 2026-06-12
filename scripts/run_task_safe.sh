#!/usr/bin/env bash
set -u
set -o pipefail

TASK_ID="${1:-}"
TIMEOUT_SECONDS="${RUN_TASK_TIMEOUT_SECONDS:-900}"

if [ -z "$TASK_ID" ]; then
  echo "Usage: bash scripts/run_task_safe.sh TASK_69"
  exit 2
fi

TASK_FILE="tasks/${TASK_ID}.md"
RESULT_FILE="tasks/${TASK_ID}_RESULT.md"
RUN_DIR="tasks/debug/${TASK_ID}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
LOG_FILE="${RUN_DIR}/${TIMESTAMP}_agy.log"
STATUS_FILE="${RUN_DIR}/${TIMESTAMP}_status.txt"
DIFF_STAT_FILE="${RUN_DIR}/${TIMESTAMP}_diff_stat.txt"
SHARE_FILE="${RUN_DIR}/${TIMESTAMP}_share_results.txt"

mkdir -p "$RUN_DIR"

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE"
  exit 2
fi

echo "=== SAFE TASK RUN START ==="
echo "Task: $TASK_ID"
echo "Timeout: ${TIMEOUT_SECONDS}s"
echo "Log: $LOG_FILE"
echo

{
  echo "# ${TASK_ID} Safe Run Checkpoint"
  echo
  echo "## Status"
  echo
  echo "IN_PROGRESS"
  echo
  echo "## Started At"
  echo
  echo "$TIMESTAMP"
  echo
  echo "## Runner"
  echo
  echo "scripts/run_task_safe.sh"
  echo
  echo "## Log File"
  echo
  echo "$LOG_FILE"
  echo
  echo "## Pre-Run Git Status"
  echo
  echo '```text'
  git status --short
  echo '```'
  echo
} > "$RESULT_FILE"

git status --short > "$STATUS_FILE"
git diff --stat > "$DIFF_STAT_FILE"

echo "Running AGY..."
echo

set +e
timeout "$TIMEOUT_SECONDS" agy --dangerously-skip-permissions -p "/run-task" 2>&1 | tee "$LOG_FILE"
AGY_EXIT=${PIPESTATUS[0]}
set -e

POST_TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"

{
  echo
  echo "## Finished At"
  echo
  echo "$POST_TIMESTAMP"
  echo
  echo "## AGY Exit Code"
  echo
  echo "$AGY_EXIT"
  echo
  echo "## Post-Run Git Status"
  echo
  echo '```text'
  git status --short
  echo '```'
  echo
  echo "## Post-Run Diff Stat"
  echo
  echo '```text'
  git diff --stat
  echo '```'
  echo
} >> "$RESULT_FILE"

if [ "$AGY_EXIT" -eq 124 ]; then
  {
    echo "## Final Status"
    echo
    echo "TIMED_OUT"
    echo
    echo "## Required Human Action"
    echo
    echo "AGY exceeded ${TIMEOUT_SECONDS}s. Do not rerun blindly."
    echo
    echo "Inspect:"
    echo
    echo "- $LOG_FILE"
    echo "- $STATUS_FILE"
    echo "- $DIFF_STAT_FILE"
    echo "- $RESULT_FILE"
    echo
    echo "Then decide whether to accept, revert, or resume."
  } >> "$RESULT_FILE"
elif [ "$AGY_EXIT" -ne 0 ]; then
  {
    echo "## Final Status"
    echo
    echo "FAILED"
    echo
    echo "## Required Human Action"
    echo
    echo "AGY exited non-zero. Inspect the log before retrying."
  } >> "$RESULT_FILE"
else
  {
    echo "## Final Status"
    echo
    echo "AGY_EXITED"
    echo
    echo "## Required Human Action"
    echo
    echo "Validate share_results and tests before accepting."
  } >> "$RESULT_FILE"
fi

echo
echo "Running share_results..."
bash scripts/share_results.sh 2>&1 | tee "$SHARE_FILE"

echo
echo "=== SAFE TASK RUN END ==="
echo "Task: $TASK_ID"
echo "AGY exit: $AGY_EXIT"
echo "Result: $RESULT_FILE"
echo "Log: $LOG_FILE"
echo "Share results: $SHARE_FILE"

exit "$AGY_EXIT"
