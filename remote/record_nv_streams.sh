#!/usr/bin/env bash

HEADER="${1:-recording}"
RGB_RECORD_BITRATE="${RGB_RECORD_BITRATE:-200000000}"
THERMAL_RECORD_BITRATE="${THERMAL_RECORD_BITRATE:-8000000}"

RGB_SOCKET="/tmp/rgb_nv.sock"
THERMAL_SOCKET="/tmp/thermal_nv.sock"

echo "[INFO] Waiting for NVMM socket at $RGB_SOCKET..."
while [ ! -S "$RGB_SOCKET" ]; do
  sleep 0.1
done

echo "[INFO] Waiting for NVMM socket at $THERMAL_SOCKET..."
while [ ! -S "$THERMAL_SOCKET" ]; do
  sleep 0.1
done

timestamp=$(date +%Y-%m-%d-%H-%M-%S)
rgb_output_file="video-rgb-${timestamp}_${HEADER}.ts"
thermal_output_file="video-thermal-${timestamp}_${HEADER}.ts"

echo "[INFO] Starting direct recorders"
echo "[INFO] rgb -> $rgb_output_file"
echo "[INFO] thermal -> $thermal_output_file"

exec gst-launch-1.0 -e \
  nvunixfdsrc socket-path="$RGB_SOCKET" do-timestamp=true ! \
    'video/x-raw(memory:NVMM),format=NV12,width=3840,height=2160' ! \
    queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! \
    nvvidconv interpolation-method=1 ! \
    'video/x-raw(memory:NVMM),format=NV12,width=2560,height=1440' ! \
    nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate="$RGB_RECORD_BITRATE" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false ! \
    h265parse ! \
    mpegtsmux ! \
    filesink location="$rgb_output_file" sync=false async=false \
  nvunixfdsrc socket-path="$THERMAL_SOCKET" do-timestamp=true ! \
    'video/x-raw(memory:NVMM),format=NV12,width=640,height=512' ! \
    queue leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 ! \
    nvv4l2h265enc maxperf-enable=1 control-rate=1 bitrate="$THERMAL_RECORD_BITRATE" iframeinterval=30 idrinterval=30 insert-sps-pps=true insert-vui=true EnableTwopassCBR=false ! \
    h265parse ! \
    mpegtsmux ! \
    filesink location="$thermal_output_file" sync=false async=false
