#!/bin/bash
set -e

VERBOSE=0
REMOTE_IP="10.200.91.54"
TAGS=()

# Parse flags and positional arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    -i|--ip)
      REMOTE_IP="$2"
      shift 2
      ;;
    -*)
      echo "[ERROR] Unknown option: $1"
      exit 1
      ;;
    *)
      TAGS+=("$1")
      shift
      ;;
  esac
done

# Require at least one tag
if [[ "${#TAGS[@]}" -eq 0 ]]; then
  echo "Usage: $0 [--ip <ip>] [-v|--verbose] <tag1> [tag2 ...]"
  exit 1
fi

PIDS=()

wait_for_rtsp_stream() {
  local url="$1"
  echo "[INFO] Waiting for RTSP stream at $url..."
  until gst-discoverer-1.0 "$url" &>/dev/null; do sleep 1; done
}

start_viewer() {
  local tag="$1"
  local url="rtsp://$REMOTE_IP:8554/$tag"

  wait_for_rtsp_stream "$url"
  echo "[INFO] Starting viewer for $tag"

  local gst_cmd=(gst-launch-1.0 -e rtspsrc location="$url" latency=0 protocols=tcp ! rtph265depay ! h265parse ! vah265dec ! videoconvert ! autovideosink sync=false)

  if [[ "$VERBOSE" -eq 1 ]]; then
    "${gst_cmd[@]}" &
  else
    "${gst_cmd[@]}" &>/dev/null &
  fi
  echo "${gst_cmd[@]}"
  pid=$!
  
  echo "[INFO] Starting $tag viewer started with pid $pid"
  PIDS+=($pid)
}

cleanup() {
  echo -e "\n[INFO] Cleaning up viewers..."
  for pid in "${PIDS[@]}"; do
    echo "[INFO] Killing pid $pid"
    kill "$pid" 2>/dev/null || true
  done
  exit 0
}

trap cleanup SIGINT SIGTERM SIGHUP EXIT

# start all the viewers
for tag in "${TAGS[@]}"; do
  start_viewer "$tag"
done

# wait for any of them to close and then cleanup
echo "[INFO] All viewers running. Press CTRL-C or close any viewer to stop."
wait -n "${PIDS[@]}"
