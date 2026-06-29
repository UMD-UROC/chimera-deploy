#!/usr/bin/env bash

BAG_ROOT="$HOME/ros2_ws"
BAG_NAME="rosbag2_$(date +%Y_%m_%d-%H_%M_%S)"
RGB_SOCKET="/tmp/rgb_nv.sock"
THERMAL_SOCKET="/tmp/thermal_nv.sock"
PIDS=()
STOPPING=0

cd "$BAG_ROOT" || exit 1
source /opt/ros/humble/setup.bash
source install/setup.bash

BAG_REGEX=$(paste -sd '|' "$HOME/ros2_ws/src/umd_uas/resource/rosbag_topics.txt")

echo "[INFO] Waiting for NVMM socket at $RGB_SOCKET..."
while [ ! -S "$RGB_SOCKET" ]; do
    sleep 0.1
done

echo "[INFO] Waiting for NVMM socket at $THERMAL_SOCKET..."
while [ ! -S "$THERMAL_SOCKET" ]; do
    sleep 0.1
done

"$HOME/chimera-deploy/remote/record_nv_streams.sh" "$BAG_NAME" &
p2=$!
PIDS+=("$p2")

ros2 bag record -s mcap --storage-preset-profile zstd_fast -e "$BAG_REGEX" -o "$BAG_NAME" &
p1=$!
PIDS+=("$p1")

wait_for_exit() {
    local attempts="$1"
    local i pid alive

    for ((i = 0; i < attempts; i++)); do
        alive=0
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                alive=1
                break
            fi
        done
        [ "$alive" -eq 0 ] && return 0
        sleep 0.1
    done

    return 1
}

stop() {
    [ "$STOPPING" -eq 1 ] && return
    STOPPING=1
    trap - INT TERM EXIT

    kill -INT "${PIDS[@]}" 2>/dev/null || true
    wait_for_exit 50 || kill -TERM "${PIDS[@]}" 2>/dev/null || true
    wait_for_exit 20 || kill -KILL "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
}

trap 'stop; exit 130' INT TERM
trap stop EXIT

wait -n "${PIDS[@]}"
status=$?
stop
exit "$status"
