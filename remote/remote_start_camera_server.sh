#!/bin/bash
set -e

LOCAL_IP="127.0.0.1"
VERBOSE=0
SERVER_PID=""

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--ip)
      LOCAL_IP="$2"
      shift 2
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    -*)
      echo "[ERROR] Unknown option: $1"
      exit 1
      ;;
  esac
done

cleanup() {
  echo -e "\n[INFO] Cleaning up..."
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[INFO] Stopping local multi_rtsp_server.py (pid=$SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  else
    echo "[INFO] No active server pid tracked; attempting best-effort cleanup..."
    pkill -f multi_rtsp_server.py 2>/dev/null || true
  fi
  echo "[INFO] Cleanup complete."
  exit 0
}
trap cleanup SIGINT SIGTERM

start_local_pipelines() {
  echo "[INFO] Starting local RTSP server"

  # Build command as an array to preserve spaces/parentheses in TAGS/PIPES entries
  local cmd=(env PYTHONUNBUFFERED=1 python3 -u ./multi_rtsp_server.py --remote-ip "$LOCAL_IP" --tags "${TAGS[@]}" --pipes "${PIPES[@]}")

  if [[ "$VERBOSE" -eq 1 ]]; then
    printf "[VERBOSE] Command:"; printf " %q" "${cmd[@]}"; echo
  fi

  "${cmd[@]}" &
  SERVER_PID=$!
  echo "[INFO] Server PID: $SERVER_PID"
  wait "$SERVER_PID"
}

TAGS=()
PIPES=()

# ----------------------------------------
# DEFINE TAGS AND PIPELINES HERE (appending)
# ----------------------------------------

common="video/x-raw(memory:NVMM) ! queue max-size-buffers=1 leaky=downstream ! nvv4l2h265enc control-rate=0 bitrate=1000000 peak-bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false zerolatency=true ! h265parse ! rtph265pay config-interval=1 pt=96 name=pay0 )"

TAGS+=("rgb")
PIPES+=("( nvarguscamerasrc sensor-id=0 wbmode=1 ! queue max-size-buffers=1 leaky=downstream ! video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 ! nvvidconv flip-method=2 ! $common")

TAGS+=("rgb-hires")
PIPES+=("( nvarguscamerasrc sensor-id=0 wbmode=1 ! queue max-size-buffers=1 leaky=downstream ! video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 ! nvvidconv flip-method=2 ! video/x-raw(memory:NVMM) ! queue max-size-buffers=1 leaky=downstream ! rtpvrawpay pt=96 name=pay0 )")

THERMAL_DEV=$(v4l2-ctl --list-devices | awk '/Boson: FLIR Video/{getline; print $1}')
TAGS+=("thermal")
PIPES+=("( v4l2src device=$THERMAL_DEV ! queue max-size-buffers=1 leaky=downstream ! video/x-raw,width=640,height=512,format=I420 ! nvvidconv ! $common")

TAGS+=("thermal/annotated")
PIPES+=("appsrc name=thermal_annotated is-live=true format=3 ! nvvidconv ! $common")

# Validate matching lengths
if [ "${#TAGS[@]}" -ne "${#PIPES[@]}" ]; then
  echo "[ERROR] TAGS and PIPES must have the same number of entries."
  exit 1
fi

start_local_pipelines

