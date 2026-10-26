#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/record_processes.sh"

BAG_ROOT=${BAG_ROOT:-$HOME/ros2_ws}
BAG_NAME=${BAG_NAME:-rosbag2_$(date +%Y_%m_%d-%H_%M_%S)}
BAG_DIR="$BAG_ROOT/$BAG_NAME"

cd "$BAG_ROOT"
(
  set +u
  source /opt/ros/humble/setup.bash
  source install/setup.bash
  set -u
  exec ros2 bag record -s mcap -a -o "$BAG_NAME"
) &
PIDS+=("$!")

while [ ! -d "$BAG_DIR" ]; do
  if ! kill -0 "${PIDS[0]}" 2>/dev/null; then
    # Video still needs a directory if the bag fails during startup.
    mkdir -p "$BAG_DIR"
    break
  fi
  sleep 0.1
done

start_video_recording() {
  (cd "$BAG_DIR" && exec "$@") &
  PIDS+=("$!")
}
