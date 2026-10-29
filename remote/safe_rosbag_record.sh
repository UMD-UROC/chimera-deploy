#!/usr/bin/env bash
set -euo pipefail
directory=$(dirname "$(readlink -f "$0")")
library_dir=$(/usr/bin/python3 "$directory/prepare_rosbag.py")
if [ "${1:-}" = --prepare ]; then
  echo "[INFO] Safe rosbag transport ready: $library_dir"
  exit 0
fi
export LD_LIBRARY_PATH="$library_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec ros2 bag record "$@"
