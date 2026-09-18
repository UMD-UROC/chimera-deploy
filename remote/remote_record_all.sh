#!/usr/bin/env bash

BAG_ROOT="$HOME/ros2_ws"
BAG_NAME="rosbag2_$(date +%Y_%m_%d-%H_%M_%S)"
BAG_DIR="$BAG_ROOT/$BAG_NAME"
PIDS=()
STOPPING=0

case "${UAS_NUM:-}" in
    1|d1)
        STREAMS=(pilot rgb)
        ;;
    3|d3|4|d4)
        STREAMS=(pilot thermal)
        ;;
    *)
        echo "[ERROR] Unsupported UAS_NUM='${UAS_NUM:-unset}'; expected 1, 3, or 4."
        exit 1
        ;;
esac

cd "$BAG_ROOT" || exit 1
source /opt/ros/humble/setup.bash
source install/setup.bash

echo "[INFO] Recording streams for UAS_NUM=$UAS_NUM: ${STREAMS[*]}"

ros2 bag record -s mcap -a -o "$BAG_NAME" &
p1=$!
PIDS+=("$p1")

echo "[INFO] Waiting for rosbag directory at $BAG_DIR..."
while [ ! -d "$BAG_DIR" ]; do
    if ! kill -0 "$p1" 2>/dev/null; then
        wait "$p1"
        exit "$?"
    fi
    sleep 0.1
done

(
    cd "$BAG_DIR" || exit 1
    exec "$HOME/chimera-deploy/remote/record_nv_streams.sh" "$BAG_NAME" "${STREAMS[@]}"
) &
p2=$!
PIDS+=("$p2")

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
