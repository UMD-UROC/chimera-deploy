#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash

if [ -f /home/dev/ros2_ws/install/setup.bash ]; then
    source /home/dev/ros2_ws/install/setup.bash
fi

exec "$@"
