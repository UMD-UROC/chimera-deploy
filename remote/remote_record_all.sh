#!/usr/bin/env bash

source "$(dirname "$0")/record_all_common.sh"

if [ "${RECORD_VIDEO:-1}" = 1 ]; then
  start_video_recording "$HOME/chimera-deploy/remote/record_nv_streams.sh"
fi

wait "${PIDS[0]}"
