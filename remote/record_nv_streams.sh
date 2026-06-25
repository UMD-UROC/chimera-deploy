#!/usr/bin/env bash
set -e

HEADER="${1:-recording}"
PIDS=()

start_recorder() {
  local tag="$1"
  local socket="$2"
  local width="$3"
  local height="$4"
  local bitrate="$5"

  while [ ! -S "$socket" ]; do
    sleep 0.1
  done

  local timestamp
  timestamp=$(date +%Y-%m-%d-%H-%M-%S)
  local output_file="video-${tag}-${timestamp}_${HEADER}.ts"

  echo "[INFO] Starting direct recorder for $tag"

  gst-launch-1.0 -e \
    nvunixfdsrc socket-path="$socket" do-timestamp=true ! \
    "video/x-raw(memory:NVMM),format=NV12,width=${width},height=${height}" ! \
    queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! \
    nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate="$bitrate" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false ! \
    h265parse ! \
    mpegtsmux ! \
    filesink location="$output_file" sync=false async=false &

  PIDS+=("$!")
  echo "[INFO] $tag recorder started with PID ${PIDS[-1]} -> $output_file"
}

stop() {
  kill "${PIDS[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}

trap stop INT TERM EXIT

start_recorder rgb /tmp/rgb_nv.sock 3840 2160 160000000
start_recorder thermal /tmp/thermal_nv.sock 640 512 40000000

wait -n "${PIDS[@]}"
