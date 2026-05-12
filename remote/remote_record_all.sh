#!/usr/bin/env bash

cd ~/chimera-deploy/local || exit 1

./record_rtsp_streams.sh rgb4 thermal4 &
p1=$!

cd ~/ros2_ws || exit 1
source /opt/ros/humble/setup.bash
source install/setup.bash
export BAG_REGEX=$(paste -sd '|' /home/user/ros2_ws/src/5g_drone/resource/rosbag_topics.txt)

ros2 bag record -s mcap --storage-preset-profile zstd_fast -e "$BAG_REGEX" &
p2=$!

stop() {
    kill "$p1" "$p2" 2>/dev/null
    wait
}

trap stop INT TERM EXIT

wait