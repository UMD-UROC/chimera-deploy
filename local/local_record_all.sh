#!/usr/bin/env bash

BAG_ROOT="$HOME/ros2_ws"
BAG_NAME="rosbag2_$(date +%Y_%m_%d-%H_%M_%S)"
BAG_DIR="$BAG_ROOT/$BAG_NAME"

cd "$BAG_ROOT" || exit 1
source /opt/ros/humble/setup.bash
source install/setup.bash

BAG_REGEX=$(paste -sd '|' "$HOME/ros2_ws/src/umd_uas/resource/rosbag_topics.txt")

ros2 bag record -s mcap --storage-preset-profile zstd_fast -e "$BAG_REGEX" -o "$BAG_NAME" &
p1=$!

while [ ! -d "$BAG_DIR" ]; do
    sleep 0.1
done

cd "$BAG_DIR" || exit 1
"$HOME/chimera-deploy/remote/record_rtsp_streams.sh" rgbl4 thermall4 &
p2=$!

stop() {
    kill "$p1" "$p2" 2>/dev/null
    wait
}

trap stop INT TERM EXIT

wait