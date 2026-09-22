#!/usr/bin/env bash

# Minimal aliases for a provisioned aircraft. The flight stack runs in the
# px4-sim-stack aircraft container; native ROS launch aliases are legacy.

alias cdd='cd ~/chimera-deploy'
alias pxs='cd ~/px4-sim-stack && ./px4sim'

# Read-only ROS environment helpers for diagnostics. Do not launch native ROS
# onboard: it conflicts with the aircraft container's MAVROS and SCF4.
alias rs='source /opt/ros/humble/setup.bash'
alias ws='source ~/ros2_ws/install/setup.bash'
alias cdr='cd ~/ros2_ws; rs; ws'
alias cd5='cdr; cd src/5g_drone'
