#!/usr/bin/env bash
set -euo pipefail

export __GL_THREADED_OPTIMIZATIONS=0
exec /opt/Foxglove/foxglove-studio "$@"
