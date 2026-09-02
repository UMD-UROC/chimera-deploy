#!/usr/bin/env bash
# QGroundControl @VERSION@ launcher (containerised runtime).
#
# Installed by local/qgc/quickstart.sh as ~/.local/bin/qgroundcontrol-v@VERSION@
# on hosts whose glibc is older than the AppImage requires. The container holds
# no state: the settings file, flight logs, map tile cache, network stack and
# serial devices are all the host's. Uninstalling is deleting this script and
# the image.
#
# Rebuild the image after editing the Dockerfile:
#   ./local/qgc/quickstart.sh --rebuild
set -euo pipefail

VERSION=@VERSION@
IMAGE=@IMAGE@

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image $IMAGE is missing. Run ./local/qgc/quickstart.sh to build it." >&2
    exit 1
fi

# X11: hand over the display socket plus a cookie for it. The GDM cookie lives
# outside $HOME and is not readable from inside the container, so merge a
# wildcard-host copy into a throwaway file that is.
XAUTH=$(mktemp /tmp/.qgc-xauth-XXXXXX)
trap 'rm -f "$XAUTH"' EXIT
xauth nlist "${DISPLAY:-:0}" 2>/dev/null \
    | sed -e 's/^..../ffff/' \
    | xauth -f "$XAUTH" nmerge - 2>/dev/null || true
chmod 644 "$XAUTH"

USER_NAME=$(id -un)

ARGS=(
    --rm
    --name "qgc-${VERSION}-$$"
    # Host networking keeps every address in the settings file literally true:
    # the UDP links, the MAVLink forward, and the local map tile server.
    --network host
    --ipc host
    -e "DISPLAY=${DISPLAY:-:0}"
    -e XAUTHORITY=/tmp/.qgc-xauth
    -e QT_X11_NO_MITSHM=1
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw
    -v "$XAUTH:/tmp/.qgc-xauth:ro"
    # The real settings, not a copy, so a change made here is a change made
    # everywhere - including for a native QGroundControl on the same machine.
    -v "$HOME/.config/QGroundControl:/home/$USER_NAME/.config/QGroundControl:rw"
    -v "$HOME/Documents/QGroundControl:/home/$USER_NAME/Documents/QGroundControl:rw"
    -v "$HOME/.cache/QGCMapCache300:/home/$USER_NAME/.cache/QGCMapCache300:rw"
    # Serial radios, autopilots and joysticks are hotplugged, so bind /dev
    # wholesale rather than naming devices that may not exist at launch.
    # udev's database goes with it so Qt can enumerate them.
    -v /dev:/dev
    -v /run/udev:/run/udev:ro
    --device /dev/dri
)

for grp in video dialout plugdev input; do
    gid=$(getent group "$grp" | cut -d: -f3)
    [[ -n "$gid" ]] && ARGS+=( --group-add "$gid" )
done

# QGroundControl 4 stored settings under the organisation "QGroundControl.org".
# Carry it through when it exists, so an older config is not stranded.
[[ -d "$HOME/.config/QGroundControl.org" ]] && ARGS+=(
    -v "$HOME/.config/QGroundControl.org:/home/$USER_NAME/.config/QGroundControl.org:rw" )

# NVIDIA GL. Without this the container has no NVIDIA userspace driver, GLX
# falls back to software and the map crawls. DRIVER_CAPABILITIES must include
# graphics; the container toolkit's default of "utility" ships no GL at all.
DOCKER_RUNTIMES=$(docker info --format '{{.Runtimes}}' 2>/dev/null || true)
if [[ $DOCKER_RUNTIMES == *nvidia* ]] && command -v nvidia-smi >/dev/null 2>&1; then
    ARGS+=( --gpus all -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility,display )
fi

# Alert tones.
PULSE_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native"
if [[ -S "$PULSE_SOCK" ]]; then
    ARGS+=( -v "$PULSE_SOCK:/tmp/pulse-native:rw" -e PULSE_SERVER=unix:/tmp/pulse-native )
fi

# Spoken alerts. QGroundControl speaks through speech-dispatcher, a separate
# daemon from PulseAudio, so it needs its socket handed over separately.
SPEECH_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/speech-dispatcher/speechd.sock"
if [[ -S "$SPEECH_SOCK" ]]; then
    ARGS+=( -v "$SPEECH_SOCK:/tmp/speechd.sock:rw" -e SPEECHD_ADDRESS=unix_socket:/tmp/speechd.sock )
fi

exec docker run "${ARGS[@]}" "$IMAGE" "$@"
