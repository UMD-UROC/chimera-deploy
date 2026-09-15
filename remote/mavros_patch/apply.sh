#!/usr/bin/env bash
# Build a patched MAVROS that talks to PX4 v1.18.
#
# Stock MAVROS 2.14.0 asks for the autopilot capabilities with
# MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES (520). PX4 v1.18 removed that command
# and answers MAV_RESULT_UNSUPPORTED, so MAVROS falls back to a default
# capability set and drops to the deprecated MISSION_ITEM protocol. The patch
# in this directory switches the request to MAV_CMD_REQUEST_MESSAGE (512).
#
# The build goes into its own overlay workspace, so apt keeps ownership of
# /opt/ros/humble and `ccb` does not rebuild MAVROS on every launch. The `ws`
# alias sources the overlay last, which puts it ahead of the apt package.
#
# Run this on the aircraft after chimera-deploy is in place. No internet
# needed: both sources come from submodules that rsync brings over.
set -euo pipefail

PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$PATCH_DIR/../.." && pwd)"
SUBMODULES="$DEPLOY_ROOT/submodules"
WS="${MAVROS_PATCH_WS:-$HOME/mavros_ws}"
PATCH="$PATCH_DIR/0001-sys_status-request-AUTOPILOT_VERSION-via-REQUEST_MESSAGE.patch"

EXPECTED_MAVROS_VERSION=2.14.0

info() { echo "[mavros-patch] $*"; }
die()  { echo "[mavros-patch] ERROR: $*" >&2; exit 1; }

[[ -f "$PATCH" ]] || die "patch file missing: $PATCH"
[[ -d "$SUBMODULES/mavros/mavros" ]] || \
    die "submodules/mavros is empty. Run: git submodule update --init submodules/mavros"
[[ -d "$SUBMODULES/angles/angles" ]] || \
    die "submodules/angles is empty. Run: git submodule update --init submodules/angles"
[[ -d "$SUBMODULES/geographic_msgs" ]] || \
    die "submodules/geographic_msgs is empty. Stage the pinned geographic_info source"

# The patch is written against a specific MAVROS release. If the submodule moves
# and the apt package does not, the overlay would silently replace the installed
# node with a different version.
src_version=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' \
    "$SUBMODULES/mavros/mavros/package.xml" | head -1)
[[ "$src_version" == "$EXPECTED_MAVROS_VERSION" ]] || \
    die "submodules/mavros is $src_version, patch targets $EXPECTED_MAVROS_VERSION"

apt_version=$(dpkg-query -W -f='${Version}' ros-humble-mavros 2>/dev/null || true)
if [[ -n "$apt_version" && "$apt_version" != "$EXPECTED_MAVROS_VERSION"* ]]; then
    info "WARNING: apt has mavros $apt_version, overlay builds $src_version"
fi

info "workspace: $WS"
mkdir -p "$WS/src"

# Copy rather than symlink: the build applies a patch to the tree, and the
# submodule checkout must stay clean for the next `sync`.
for pkg in mavros angles; do
    rm -rf "${WS:?}/src/$pkg"
    cp -a "$SUBMODULES/$pkg" "$WS/src/$pkg"
    rm -rf "$WS/src/$pkg/.git"
done
rm -rf "$WS/src/geographic_msgs"
cp -a "$SUBMODULES/geographic_msgs" "$WS/src/geographic_msgs"
rm -rf "$WS/src/geographic_msgs/.git"

# Build the complete pinned source set. ROS Humble no longer publishes the
# mavros binary packages on every supported apt mirror, so the overlay must not
# rely on mavros_msgs or libmavconn being preinstalled.
touch "$WS/src/mavros/mavros_extras/COLCON_IGNORE"

info "applying $(basename "$PATCH")"
patch -p1 -d "$WS/src/mavros" --forward --silent < "$PATCH" \
    || die "patch did not apply to $src_version"

grep -q "MAV_CMD::REQUEST_MESSAGE" "$WS/src/mavros/mavros/src/plugins/sys_status.cpp" \
    || die "patch applied but REQUEST_MESSAGE is not in sys_status.cpp"

info "building (this takes a while on the Orin)"
# ROS setup files read unset variables, so -u has to come off around them.
set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u
cd "$WS"
# Overriding the apt mavros is the point of this workspace. It stays ABI safe
# because the submodule is pinned to the same release the apt package ships,
# which the version check above enforces.
colcon build --packages-select geographic_msgs angles mavros_msgs libmavconn mavros \
    --allow-overriding geographic_msgs mavros_msgs libmavconn mavros \
    --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

info "done. Overlay at $WS/install"
info "Confirm the ws alias sources it, then relaunch:"
info "  grep mavros_ws ~/.bash_aliases"
