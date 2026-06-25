#!/usr/bin/env bash

HEADER="${1:-recording}"
RGB_RECORD_BITRATE="${RGB_RECORD_BITRATE:-200000000}"
THERMAL_RECORD_BITRATE="${THERMAL_RECORD_BITRATE:-8000000}"
PIDS=()
STOPPING=0

record_stream() {
  local tag="$1"
  local socket="$2"
  local width="$3"
  local height="$4"
  local bitrate="$5"
  local record_width="${6:-$width}"
  local record_height="${7:-$height}"

  echo "[INFO] Waiting for NVMM socket at $socket..."
  while [ ! -S "$socket" ]; do
    sleep 0.1
  done

  local timestamp
  timestamp=$(date +%Y-%m-%d-%H-%M-%S)
  local output_file="video-${tag}-${timestamp}_${HEADER}.ts"

  echo "[INFO] Starting direct recorder for $tag -> $output_file"

  if [ "$width" = "$record_width" ] && [ "$height" = "$record_height" ]; then
    exec gst-launch-1.0 -e \
      nvunixfdsrc socket-path="$socket" do-timestamp=true ! \
      "video/x-raw(memory:NVMM),format=NV12,width=${width},height=${height}" ! \
      queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! \
      nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate="$bitrate" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false ! \
      h265parse ! \
      mpegtsmux ! \
      filesink location="$output_file" sync=false async=false
  fi

  exec gst-launch-1.0 -e \
    nvunixfdsrc socket-path="$socket" do-timestamp=true ! \
    "video/x-raw(memory:NVMM),format=NV12,width=${width},height=${height}" ! \
    queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! \
    nvvidconv interpolation-method=1 ! \
    "video/x-raw(memory:NVMM),format=NV12,width=${record_width},height=${record_height}" ! \
    nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate="$bitrate" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false ! \
    h265parse ! \
    mpegtsmux ! \
    filesink location="$output_file" sync=false async=false
}

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
  wait_for_exit 30 || kill -TERM "${PIDS[@]}" 2>/dev/null || true
  wait_for_exit 20 || kill -KILL "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
}

trap 'stop; exit 130' INT TERM
trap stop EXIT

record_stream rgb /tmp/rgb_nv.sock 3840 2160 "$RGB_RECORD_BITRATE" 2560 1440 &
PIDS+=("$!")
echo "[INFO] rgb recorder process started with PID ${PIDS[-1]}"

record_stream thermal /tmp/thermal_nv.sock 640 512 "$THERMAL_RECORD_BITRATE" &
PIDS+=("$!")
echo "[INFO] thermal recorder process started with PID ${PIDS[-1]}"

wait -n "${PIDS[@]}"
status=$?
stop
exit "$status"
