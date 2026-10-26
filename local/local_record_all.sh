#!/usr/bin/env bash

source "$(dirname "$0")/../remote/record_all_common.sh"
if [ "${RECORD_VIDEO:-1}" = 1 ]; then
  # px4sim supplies the fleet's streams. Keep the standalone script's default.
  # shellcheck disable=SC2206
  streams=(${RECORD_STREAMS:-pilotl4 rgbl4 thermall4})
  start_video_recording "$HOME/chimera-deploy/remote/record_rtsp_streams.sh" --header "$BAG_NAME" "${streams[@]}"
fi
wait_recorders
