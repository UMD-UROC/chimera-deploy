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

common="protocols=udp latency=0 drop-on-late=true ! rtph265depay ! queue2 leaky=downstream max-size-buffers=1 ! h265parse ! video/x-h265,stream-format=byte-stream,alignment=au ! rtph265pay pt=96 config-interval=1 name=pay0 )"

#TAGS+=("rgb1")
#PIPES+=("( rtspsrc location=rtsp://10.200.91.51:8900/live $common")

#TAGS+=("rgb2")
#PIPES+=("( rtspsrc location=rtsp://10.200.91.52:8900/live $common")

TAGS+=("rgb3")
PIPES+=("( rtspsrc location=rtsp://10.200.91.53:8554/rgb $common")

TAGS+=("thermal3")
PIPES+=("( rtspsrc location=rtsp://10.200.91.53:8554/thermal $common")

TAGS+=("rgb4")
PIPES+=("( rtspsrc location=rtsp://10.200.91.54:8554/rgb $common")

TAGS+=("thermal4")
PIPES+=("( rtspsrc location=rtsp://10.200.91.54:8554/thermal $common")

# Validate matching lengths
if [ "${#TAGS[@]}" -ne "${#PIPES[@]}" ]; then
  echo "[ERROR] TAGS and PIPES must have the same number of entries."
  exit 1
fi

start_local_pipelines

