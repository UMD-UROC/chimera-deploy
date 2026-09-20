#!/usr/bin/env bash

source "$(dirname "$0")/record_all_common.sh"

case "${UAS_NUM:-}" in
    1|d1)
        STREAMS=(pilot rgb)
        ;;
    3|d3|4|d4)
        STREAMS=(pilot thermal)
        ;;
    *)
        echo "[ERROR] Unsupported UAS_NUM='${UAS_NUM:-unset}'; expected 1, 3, or 4."
        exit 1
        ;;
esac

echo "[INFO] Recording streams for UAS_NUM=$UAS_NUM: ${STREAMS[*]}"
if [ "${RECORD_VIDEO:-1}" = 1 ]; then
  start_video_recording "$HOME/chimera-deploy/remote/record_nv_streams.sh" "${STREAMS[@]}"
fi

wait -n "${PIDS[@]}"
