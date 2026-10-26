#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/record_processes.sh"

VERBOSE=0
HEADER=""
REMOTE_IP="127.0.0.1"
TAGS=()

# Parse flags and positional arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    -h|--header)
      HEADER="$2"
      shift 2
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

start_recorder() {
  local tag="$1"
  local url="rtsp://$REMOTE_IP:8554/$tag"

  local timestamp
  timestamp=$(date +%Y-%m-%d-%H-%M-%S)
  local output_file="video-${tag}-${timestamp}_${HEADER}"

  echo "[INFO] Starting recorder for $tag"

  local gst_cmd=(gst-launch-1.0 -e)
  [[ "$VERBOSE" -eq 1 ]] || gst_cmd+=(-q)
  gst_cmd+=(rtspsrc location="$url" latency=0 protocols=tcp ! rtph265depay ! h265parse ! mpegtsmux ! filesink location="$output_file.ts")
  # Each source connects independently. Keep errors in the session log.
  "${gst_cmd[@]}" &

  local pid=$!
  PIDS+=("$pid")
  echo "[INFO] $tag recorder started with PID $pid → $output_file"
}

for tag in "${TAGS[@]}"; do
  start_recorder "$tag"
done

wait_recorders
