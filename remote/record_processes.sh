#!/usr/bin/env bash
# Shared lifetime for a bag recorder or a group of video recorders.

PIDS=()
STOPPING=0

stop() {
  [ "$STOPPING" -eq 1 ] && return
  STOPPING=1
  # The session supervisor can signal the group while a parent also stops us.
  trap '' INT TERM
  trap - EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    # Exited children can leave saved PIDs that another process later reuses.
    local running=()
    mapfile -t running < <(jobs -pr)
    if [ "${#running[@]}" -gt 0 ]; then
      kill -INT "${running[@]}" 2>/dev/null || true
    fi
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}

wait_recorders() {
  local pid result status=0
  # Wait for every child, even when another child fails.
  for pid in "${PIDS[@]}"; do
    if wait "$pid"; then
      :
    else
      result=$?
      echo "[ERROR] Recorder process $pid exited with status $result" >&2
      status=$result
    fi
  done
  return "$status"
}

trap 'stop; exit 130' INT TERM
trap stop EXIT
