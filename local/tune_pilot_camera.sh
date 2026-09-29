#!/usr/bin/env bash
# Try pilot camera settings on a drone and measure what reaches this laptop.
#
#   ./local/tune_pilot_camera.sh [-d IP] 'label|nvarguscamerasrc options' ...
#   ./local/tune_pilot_camera.sh [-d IP] --measure [label]
#   ./local/tune_pilot_camera.sh [-d IP] --reset
#
# Each candidate goes into the drone's systemd environment as PILOT_CAMERA,
# which rtsp_config.py prefers over its committed default, and rcam restarts.
# Nothing tracked by git changes, so sync is never blocked by a tuning session.
# The override lasts until --reset or a reboot; sync does not see it. When a
# setting wins, commit it as PILOT_CAMERA in remote/rtsp_config.py.
#
# Prints the settings rcam reports it started with, then R/G and B/G (1.00 is
# neutral), mean and 99.5th percentile luma, and the share of clipped pixels.
# Frames land in /tmp/pilot_tune. Needs ffmpeg, python3-numpy, python3-pil.
# See remote/CAMERA_TUNING.md.
set -u

DRONE=10.200.142.63
DRONE_USER=user
OUT=/tmp/pilot_tune
SETTLE_SECONDS=8   # auto exposure and white balance converge in about 5

if [ "${1:-}" = -d ]; then
  DRONE="$2"; shift 2
fi
[ "$#" -gt 0 ] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
D="$DRONE_USER@$DRONE"
mkdir -p "$OUT"

measure() {
  local label="$1" file="$OUT/$1.jpg"
  timeout 25 ffmpeg -loglevel error -rtsp_transport tcp -i "rtsp://$DRONE:8554/pilot" \
    -frames:v 1 -vf scale=960:540 -y "$file" </dev/null
  python3 - "$file" <<'PY'
import os, sys
import numpy as np
from PIL import Image
f = sys.argv[1]
if not os.path.exists(f) or os.path.getsize(f) == 0:
    print("   NO FRAME - is rcam up?"); sys.exit(1)
a = np.asarray(Image.open(f).convert("RGB")).astype(float)
r, g, b = a.reshape(-1, 3).mean(0)
y = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
clipped = (a >= 250).any(2).mean() * 100
print(f"   R/G={r/g:.2f} B/G={b/g:.2f} | meanY={y.mean():.0f}"
      f" white(p99.5)={np.percentile(y, 99.5):.0f} clipped={clipped:.2f}% | {f}")
PY
}

# restart rcam with PILOT_CAMERA set to $1, or unset when $1 is empty
apply() {
  local options="$1" since
  since="$(ssh -n -o BatchMode=yes "$D" "date '+%F %T'")"
  printf '%s\n%s\n' "$PW" "$options" | ssh -o BatchMode=yes "$D" '
    read -r pw; read -r options
    if [ -n "$options" ]; then
      printf "%s\n" "$pw" | sudo -S -p "" systemctl set-environment "PILOT_CAMERA=$options"
    else
      printf "%s\n" "$pw" | sudo -S -p "" systemctl unset-environment PILOT_CAMERA
    fi && printf "%s\n" "$pw" | sudo -S -p "" systemctl restart rcam' || return 1
  for _ in $(seq 40); do
    sleep 1
    ssh -n -o BatchMode=yes "$D" \
      "journalctl -u rcam --since '$since' --no-pager | grep -q 'Starting repeat capture'" && break
  done
  ssh -n -o BatchMode=yes "$D" "journalctl -u rcam --since '$since' --no-pager -o cat \
    | grep -oE 'pilot-fork camera:.*|producer ERROR.*' | tail -1" | sed 's/^/   /'
  sleep "$SETTLE_SECONDS"
}

case "$1" in
  --measure)
    measure "${2:-now}"
    exit
    ;;
esac

read -rsp "sudo password for $D: " PW; echo >&2

if [ "$1" = --reset ]; then
  echo "== reset: rcam back to the committed PILOT_CAMERA"
  apply '' && measure reset
  exit
fi

for candidate in "$@"; do
  label="${candidate%%|*}"
  options="${candidate#*|}"
  [ "$label" != "$candidate" ] || { echo "skipping '$candidate': want 'label|options'"; continue; }
  echo "== $label: $options"
  apply "$options" && measure "$label"
done
echo "Still overriding. Keep a winner by committing it as PILOT_CAMERA, then run --reset."
