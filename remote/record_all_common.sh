#!/usr/bin/env bash

set -euo pipefail

BAG_ROOT=${BAG_ROOT:-$HOME/ros2_ws}
BAG_NAME=${BAG_NAME:-rosbag2_$(date +%Y_%m_%d-%H_%M_%S)}
BAG_DIR="$BAG_ROOT/$BAG_NAME"
PIDS=()
STOPPING=0

cd "$BAG_ROOT"
set +u
source /opt/ros/humble/setup.bash
source install/setup.bash
set -u

ros2 bag record -s mcap -a -o "$BAG_NAME" &
PIDS+=("$!")

while [ ! -d "$BAG_DIR" ]; do

  kill -0 "${PIDS[0]}" 2>/dev/null || exit 1
  sleep 0.1
done

start_video_recording() {
  (cd "$BAG_DIR" && exec "$1" "$BAG_NAME" "${@:2}") &
  PIDS+=("$!")
}

stop() {
  [ "$STOPPING" -eq 1 ] && return
  STOPPING=1
  trap - INT TERM EXIT
  kill -INT "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
}

trap 'stop; exit 130' INT TERM
trap stop EXIT
