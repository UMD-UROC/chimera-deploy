#!/bin/bash
set -e

VERBOSE=0
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

wait_for_rtsp_stream() {
  local url="$1"
  echo "[INFO] Waiting for RTSP stream at $url..."
  until gst-discoverer-1.0 "$url" > /dev/null 2>&1; do
    sleep 1
  done
}

start_recorder() {
  local tag="$1"
  local url="rtsp://$REMOTE_IP:8554/$tag"

  wait_for_rtsp_stream "$url"

  local timestamp
  timestamp=$(date +%Y-%m-%d-%H-%M-%S)
  local output_file="video-${tag}-${timestamp}_${HEADER}"

  echo "[INFO] Starting recorder for $tag"

  # change recording here
  local gst_cmd=(gst-launch-1.0 -e rtspsrc location="$url" latency=0 protocols=tcp ! rtph265depay ! h265parse ! mpegtsmux ! filesink location="$output_file.ts") # stream safe container

  if [[ "$VERBOSE" -eq 1 ]]; then
    "${gst_cmd[@]}" &
  else
    "${gst_cmd[@]}" &>/dev/null &
  fi

  local pid=$!
  PIDS+=("$pid")
  echo "[INFO] $tag recorder started with PID $pid → $output_file"
}

for tag in "${TAGS[@]}"; do
  start_recorder "$tag"
done

wait -n "${PIDS[@]}"
