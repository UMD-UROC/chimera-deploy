#!/usr/bin/env bash
set -euo pipefail

BAG_ROOT="$HOME/ros2_ws"
BAG_NAME="rosbag_$(date +%Y%m%d_%H%M%S)"
BAG_DIR="$BAG_ROOT/$BAG_NAME"

cd "$BAG_ROOT" || exit 1
source /opt/ros/humble/setup.bash
source install/setup.bash

BAG_REGEX=$(paste -sd '|' "$HOME/ros2_ws/src/5g_drone/resource/rosbag_topics.txt")

ros2 bag record \
    -s mcap \
    --storage-preset-profile zstd_fast \
    -e "$BAG_REGEX" \
    -o "$BAG_NAME" &
p_bag=$!

# Wait for ros2 bag to create the output folder
until [ -d "$BAG_DIR" ]; do
    sleep 0.1
done

(
    cd "$BAG_DIR" || exit 1
    "$HOME/chimera-deploy/remote/record_rtsp_streams.sh" rgb thermal
) &
p_video=$!

stop() {
    kill "$p_video" "$p_bag" 2>/dev/null || true
    wait 2>/dev/null || true
}

trap stop INT TERM EXIT

wait