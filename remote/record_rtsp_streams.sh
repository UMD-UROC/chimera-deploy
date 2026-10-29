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

  local gst_cmd=(/usr/bin/python3 "$(dirname "$(readlink -f "$0")")/run_gst_recording.py")
  gst_cmd+=(rtspsrc location="$url" latency=200 protocols=tcp ! rtph265depay ! h265parse name=record_parser config-interval=-1 ! video/x-h265,stream-format=byte-stream,alignment=au ! mpegtsmux ! filesink location="$output_file.ts" sync=false async=false buffer-mode=unbuffered)
  python3 "$(dirname "$(readlink -f "$0")")/record_video_worker.py" "$output_file.ts" -- "${gst_cmd[@]}" &

  local pid=$!
  PIDS+=("$pid")
  echo "[INFO] $tag recorder started with PID $pid → $output_file"
}

for tag in "${TAGS[@]}"; do
  start_recorder "$tag"
done

wait_recorders
