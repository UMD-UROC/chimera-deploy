#!/usr/bin/env bash

HEADER="${1:-recording}"
PILOT_RECORD_BITRATE="${PILOT_RECORD_BITRATE:-200000000}"
RGB_RECORD_BITRATE="${RGB_RECORD_BITRATE:-25000000}"
THERMAL_RECORD_BITRATE="${THERMAL_RECORD_BITRATE:-8000000}"

STREAMS=("${@:2}")
if [[ "${#STREAMS[@]}" -eq 0 ]]; then
  STREAMS=(pilot rgb thermal)
fi

PILOT_SOCKET="/tmp/pilot_nv.sock"
RGB_SOCKET="/tmp/rgb_nv.sock"
THERMAL_SOCKET="/tmp/thermal_nv.sock"

for stream in "${STREAMS[@]}"; do
  case "$stream" in
    pilot) socket="$PILOT_SOCKET" ;;
    rgb) socket="$RGB_SOCKET" ;;
    thermal) socket="$THERMAL_SOCKET" ;;
    *) echo "[ERROR] Unknown stream '$stream' (expected pilot, rgb, or thermal)."; exit 1 ;;
  esac
  echo "[INFO] Waiting for NVMM socket at $socket..."
  while [ ! -S "$socket" ]; do
    sleep 0.1
  done
done

timestamp=$(date +%Y-%m-%d-%H-%M-%S)
pilot_output_file="video-pilot-${timestamp}_${HEADER}.ts"
rgb_output_file="video-rgb-${timestamp}_${HEADER}.ts"
thermal_output_file="video-thermal-${timestamp}_${HEADER}.ts"

echo "[INFO] Starting direct recorders: ${STREAMS[*]}"

PIDS=()
STOPPING=0

start_recorder() {
  local stream="$1"
  local socket output_file
  local -a gst_cmd

  case "$stream" in
    pilot)
      socket="$PILOT_SOCKET"
      output_file="$pilot_output_file"
      echo "[INFO] pilot -> $output_file"
      gst_cmd=(
        gst-launch-1.0 -e
        nvunixfdsrc "socket-path=$socket" do-timestamp=true !
        'video/x-raw(memory:NVMM),format=NV12,width=3840,height=2160' !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvvidconv interpolation-method=1 !
        'video/x-raw(memory:NVMM),format=NV12,width=2560,height=1440' !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 "bitrate=$PILOT_RECORD_BITRATE" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse ! mpegtsmux ! filesink "location=$output_file" sync=false async=false
      )
      ;;
    rgb)
      socket="$RGB_SOCKET"
      output_file="$rgb_output_file"
      echo "[INFO] rgb -> $output_file"
      gst_cmd=(
        gst-launch-1.0 -e
        nvunixfdsrc "socket-path=$socket" do-timestamp=true !
        'video/x-raw(memory:NVMM),format=NV12,width=1920,height=1080' !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 "bitrate=$RGB_RECORD_BITRATE" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse ! mpegtsmux ! filesink "location=$output_file" sync=false async=false
      )
      ;;
    thermal)
      socket="$THERMAL_SOCKET"
      output_file="$thermal_output_file"
      echo "[INFO] thermal -> $output_file"
      gst_cmd=(
        gst-launch-1.0 -e
        nvunixfdsrc "socket-path=$socket" do-timestamp=true !
        'video/x-raw(memory:NVMM),format=NV12,width=640,height=512' !
        queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 !
        nvv4l2h265enc maxperf-enable=1 control-rate=1 "bitrate=$THERMAL_RECORD_BITRATE" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false !
        h265parse ! mpegtsmux ! filesink "location=$output_file" sync=false async=false
      )
      ;;
  esac

  "${gst_cmd[@]}" &
  PIDS+=("$!")
}

stop() {
  [ "$STOPPING" -eq 1 ] && return
  STOPPING=1
  trap - INT TERM EXIT
  kill -INT "${PIDS[@]}" 2>/dev/null || true
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap 'stop; exit 130' INT TERM
trap stop EXIT

for stream in "${STREAMS[@]}"; do
  case "$stream" in
    pilot|rgb|thermal) start_recorder "$stream" ;;
    *) echo "[ERROR] Unknown stream '$stream'"; exit 1 ;;
  esac
done

wait -n "${PIDS[@]}"
status=$?
stop
exit "$status"
