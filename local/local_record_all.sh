#!/usr/bin/env bash

source "$(dirname "$0")/../remote/record_all_common.sh"
start_video_recording "$HOME/chimera-deploy/remote/record_rtsp_streams.sh" pilotl4 rgbl4 thermall4
wait -n "${PIDS[@]}"
