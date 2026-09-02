#!/bin/bash

set -e

REMOTE_USER="j1"
REMOTE_IP="10.200.91.54"
VERBOSE=0

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--user)
      REMOTE_USER="$2"
      shift 2
      ;;
    -i|--ip)
      REMOTE_IP="$2"
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
  echo "[INFO] Closing any ssh session..."
  ssh -n -q -o ConnectionAttempts=1 -o ConnectTimeout=1 "$REMOTE_USER@$REMOTE_IP" "pkill -f multi_rtsp_server.py" 2>/dev/null || :
  echo "[INFO] Cleanup complete."
  exit 0
}
trap cleanup SIGINT

check_ssh() {
  local total_secs=90
  local per_try=${TIMEOUT:-1}   # seconds per attempt (defaults to 1s)
  local deadline=$((SECONDS + total_secs))

  echo "[INFO] Attempting to connect to $REMOTE_USER@$REMOTE_IP for ${total_secs}s (Ctrl-C to cancel)"

  while (( SECONDS < deadline )); do
    if timeout "${per_try}s" ssh -n -q \
         -o BatchMode=yes \
         -o ConnectionAttempts=1 \
         -o StrictHostKeyChecking=accept-new \
         -o ConnectTimeout="${per_try}" \
         "$REMOTE_USER@$REMOTE_IP" "exit" 2>/dev/null; then
      echo "[INFO] SSH connection valid"
      return 0
    fi
    sleep 0.5
  done

  echo "[ERROR] SSH requires a password or failed to connect within ${total_secs}s."
  echo "[INFO] To copy rsa key, run:"
  echo "  ssh-keygen -t rsa -b 4096"
  echo "  ssh-copy-id -i ~/.ssh/id_rsa.pub $REMOTE_USER@$REMOTE_IP"
  exit 1
}

check_cam_server() {
  echo "[INFO] Syncing remote camera server"
  rsync -avzc multi_rtsp_server.py $REMOTE_USER@$REMOTE_IP:/home/$REMOTE_USER 1>/dev/null
}

start_remote_pipelines() {
  echo "[INFO] Starting remote RTSP server"

  REMOTE_IP_ARG="--remote-ip $REMOTE_IP"  
  TAG_ARGS="--tags"
  PIPE_ARGS="--pipes"
  for tag in "${TAGS[@]}"; do TAG_ARGS+=" \"$tag\""; done
  for pipe in "${PIPES[@]}"; do PIPE_ARGS+=" \"$pipe\""; done

  remote_cmd="PYTHONUNBUFFERED=1 python3 -u /home/$REMOTE_USER/multi_rtsp_server.py $REMOTE_IP_ARG $TAG_ARGS $PIPE_ARGS"

  if [[ "$VERBOSE" -eq 1 ]]; then
    echo "[VERBOSE] SSH command: $remote_cmd"
  fi

  # -tt allocates a TTY so Python line-buffers; -o LogLevel=ERROR keeps it quiet
  ssh -tt -o LogLevel=ERROR -o ServerAliveInterval=1 -o ServerAliveCountMax=120 "$REMOTE_USER@$REMOTE_IP" "$remote_cmd"
}

check_ssh
check_cam_server

TAGS=()
PIPES=()

# Ask the drone for the lowest-numbered capture node whose card name contains
# $1, optionally narrowed to one advertising pixel format $2. Needed because
# the C1 PRO and the Boson shuffle /dev/videoN between boots, and because the
# C1 PRO puts its H.264 and its MJPEG feeds on separate nodes under the same
# card name.
remote_find_v4l2_device() {
  ssh "$REMOTE_USER@$REMOTE_IP" bash -s -- "$1" "${2:-}" <<'REMOTE_SCRIPT'
name="$1"; fmt="$2"
while read -r dev; do
  formats=$(v4l2-ctl -d "$dev" --list-formats 2>/dev/null) || continue
  grep -q "Pixel Format" <<<"$formats" || continue
  if [ -z "$fmt" ] || grep -q "'$fmt'" <<<"$formats"; then
    printf '%s\n' "$dev"
    exit 0
  fi
done < <(v4l2-ctl --list-devices 2>/dev/null |
  awk -v n="$name" 'index($0, n) { grab = 1; next } /^[^[:space:]]/ { grab = 0 } grab && /\/dev\/video/ { print $1 }')
exit 1
REMOTE_SCRIPT
}

# ----------------------------------------
# DEFINE TAGS AND PIPELINES HERE (appending)
# ----------------------------------------
common="video/x-raw(memory:NVMM) ! queue max-size-buffers=1 leaky=downstream ! nvv4l2h265enc control-rate=0 bitrate=1000000 peak-bitrate=5000000 iframeinterval=0 insert-sps-pps=true EnableTwopassCBR=false zerolatency=true ! h265parse ! rtph265pay config-interval=1 pt=96 name=pay0 )"

TAGS+=("pilot")
PIPES+=("( nvarguscamerasrc sensor-id=0 wbmode=1 ! queue max-size-buffers=1 leaky=downstream ! video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 ! nvvidconv flip-method=2 ! $common")

# A camera that is unplugged or still enumerating is a warning, not a fatal
# error: skip its stream and serve whatever else came up.
# The C1 PRO only emits compressed video, so decode before handing off to $common.
if RGB_DEV=$(remote_find_v4l2_device "C1 PRO" "H264"); then
  TAGS+=("rgb")
  PIPES+=("( v4l2src device=$RGB_DEV io-mode=2 ! video/x-h264,width=1920,height=1080 ! h264parse ! video/x-h264,stream-format=byte-stream,alignment=au ! nvv4l2decoder enable-max-performance=1 ! queue max-size-buffers=1 leaky=downstream ! nvvidconv ! $common")
else
  echo "[WARN] No C1 PRO H264 capture device found on $REMOTE_IP; skipping 'rgb' stream."
fi

if THERMAL_DEV=$(remote_find_v4l2_device "Boson: FLIR Video"); then
  TAGS+=("thermal")
  PIPES+=("( v4l2src device=$THERMAL_DEV ! queue max-size-buffers=1 leaky=downstream ! video/x-raw,width=640,height=512,format=I420 ! nvvidconv ! $common")
else
  echo "[WARN] No Boson capture device found on $REMOTE_IP; skipping 'thermal' stream."
fi

# Validate matching lengths
if [ "${#TAGS[@]}" -ne "${#PIPES[@]}" ]; then
  echo "[ERROR] TAGS and PIPES must have the same number of entries."
  exit 1
fi

start_remote_pipelines

