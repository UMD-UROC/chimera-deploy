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

# Lowest-numbered capture node whose card name contains $1, optionally narrowed
# to one advertising pixel format $2. Needed because the C1 PRO and the Boson
# shuffle /dev/videoN between boots, and because the C1 PRO puts its H.264 and
# its MJPEG feeds on separate nodes under the same card name.
find_v4l2_device() {
  local name="$1" fmt="${2:-}" dev formats
  while read -r dev; do
    formats=$(v4l2-ctl -d "$dev" --list-formats 2>/dev/null) || continue
    grep -q "Pixel Format" <<<"$formats" || continue
    if [[ -z "$fmt" ]] || grep -q "'$fmt'" <<<"$formats"; then
      printf '%s\n' "$dev"
      return 0
    fi
  done < <(v4l2-ctl --list-devices 2>/dev/null |
    awk -v n="$name" 'index($0, n) { grab = 1; next } /^[^[:space:]]/ { grab = 0 } grab && /\/dev\/video/ { print $1 }')
  return 1
}

# ----------------------------------------
# DEFINE TAGS AND PIPELINES HERE (appending)
# ----------------------------------------

common="video/x-raw(memory:NVMM) ! queue max-size-buffers=1 leaky=downstream ! nvv4l2h265enc control-rate=0 bitrate=1000000 peak-bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false zerolatency=true ! h265parse ! rtph265pay config-interval=1 pt=96 name=pay0 )"

TAGS+=("pilot")
PIPES+=("( nvarguscamerasrc sensor-id=0 wbmode=1 ! queue max-size-buffers=1 leaky=downstream ! video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 ! nvvidconv flip-method=2 ! $common")

#TAGS+=("pilot-hires")
#PIPES+=("( nvarguscamerasrc sensor-id=0 wbmode=1 ! queue max-size-buffers=1 leaky=downstream ! video/x-raw(memory:NVMM),width=3840,height=2160,framerate=30/1 ! nvvidconv flip-method=2 ! video/x-raw(memory:NVMM) ! queue max-size-buffers=1 leaky=downstream ! nvv4l2h265enc control-rate=0 bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false zerolatency=true ! h265parse ! rtph265pay config-interval=1 pt=96 name=pay0 )")

# A camera that is unplugged or still enumerating is a warning, not a fatal
# error: skip its streams and serve whatever else came up.
# The C1 PRO only emits compressed video, so decode before handing off to $common.
if RGB_DEV=$(find_v4l2_device "C1 PRO" "H264"); then
  TAGS+=("rgb")
  PIPES+=("( v4l2src device=$RGB_DEV io-mode=2 ! video/x-h264,width=1920,height=1080 ! h264parse ! video/x-h264,stream-format=byte-stream,alignment=au ! nvv4l2decoder enable-max-performance=1 ! queue max-size-buffers=1 leaky=downstream ! nvvidconv ! $common")
else
  echo "[WARN] No C1 PRO H264 capture device found; skipping 'rgb' stream."
fi

# The annotated feed is rendered from the Boson frames, so it goes with it.
if THERMAL_DEV=$(find_v4l2_device "Boson: FLIR Video"); then
  TAGS+=("thermal")
  PIPES+=("( v4l2src device=$THERMAL_DEV ! queue max-size-buffers=1 leaky=downstream ! video/x-raw,width=640,height=512,format=I420 ! nvvidconv ! $common")

  TAGS+=("thermal/annotated")
  PIPES+=("appsrc name=thermal_annotated is-live=true format=3 ! nvvidconv ! $common")
else
  echo "[WARN] No Boson capture device found; skipping 'thermal' and 'thermal/annotated' streams."
fi

# Validate matching lengths
if [ "${#TAGS[@]}" -ne "${#PIPES[@]}" ]; then
  echo "[ERROR] TAGS and PIPES must have the same number of entries."
  exit 1
fi

if [ "${#TAGS[@]}" -eq 0 ]; then
  echo "[WARN] No cameras available; nothing to serve. Exiting."
  exit 0
fi

start_local_pipelines

