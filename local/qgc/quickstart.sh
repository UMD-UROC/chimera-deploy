#!/usr/bin/env bash
# QGroundControl, from nothing to a launchable app, in one command.
#
#   ./local/qgc/quickstart.sh
#
# It downloads a pinned QGroundControl release, checks it against a recorded
# SHA-256, works out whether this host can run it directly, installs it either
# natively or inside a minimal container, seeds the settings in this directory
# if you have none, and registers a desktop entry named "QGC <version>".
#
# Running it twice is safe. It never overwrites settings you already have
# unless you pass --force-settings.
set -euo pipefail

# ---------------------------------------------------------------- pinned release
# Bump these together. Digests come from the release's GitHub API entry:
#   curl -s https://api.github.com/repos/mavlink/qgroundcontrol/releases/tags/vX.Y.Z \
#     | python3 -c 'import json,sys;[print(a["name"],a.get("digest")) for a in json.load(sys.stdin)["assets"]]'
QGC_VERSION=5.1.4
SHA256_x86_64=1c4ac089abfaac6c6fcd75c7b477ea18da1bc3592cddca5ab1a19c1a13410e65
SHA256_aarch64=901aa3d53648c483b1ed64f665cebce4eb3ac74ddd41eaaa56d151afa8dd15a7

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="$HERE/.cache"
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons"
DESKTOP_DIR="$HOME/.local/share/applications"
CONFIG_DIR="$HOME/.config/QGroundControl"

MODE=auto
FORCE_SETTINGS=0
DO_APT=1
REBUILD=0

usage() {
    cat <<EOF
Usage: ${0##*/} [options]

  --version X.Y.Z     install this release instead of the pinned $QGC_VERSION
                      (skips the checksum check, since the pin will not match)
  --mode MODE         auto (default), native, or container
  --force-settings    overwrite ~/.config/QGroundControl/QGroundControl.ini
                      with this repo's defaults
  --no-apt            skip the apt step, which is the only part needing sudo
  --rebuild           rebuild the container image even if it already exists
  -h, --help          this text
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) QGC_VERSION="$2"; SHA256_x86_64=""; SHA256_aarch64=""; shift 2 ;;
        --mode) MODE="$2"; shift 2 ;;
        --force-settings) FORCE_SETTINGS=1; shift ;;
        --no-apt) DO_APT=0; shift ;;
        --rebuild) REBUILD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -m)" in
    x86_64)        ARCH_TAG=x86_64;  EXPECT_SHA="$SHA256_x86_64" ;;
    aarch64|arm64) ARCH_TAG=aarch64; EXPECT_SHA="$SHA256_aarch64" ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
esac

APPIMAGE_NAME="QGroundControl-${ARCH_TAG}.AppImage"
APPIMAGE="$CACHE/QGroundControl-v${QGC_VERSION}-${ARCH_TAG}.AppImage"
URL="https://github.com/mavlink/qgroundcontrol/releases/download/v${QGC_VERSION}/${APPIMAGE_NAME}"

TARGET_BIN="$BIN_DIR/qgroundcontrol-v${QGC_VERSION}"
DESKTOP_FILE="$DESKTOP_DIR/qgroundcontrol-v${QGC_VERSION}.desktop"
IMAGE="qgc:${QGC_VERSION}"

mkdir -p "$CACHE" "$BIN_DIR" "$ICON_DIR" "$DESKTOP_DIR"

# ------------------------------------------------------------------ 1. download
say "QGroundControl $QGC_VERSION ($ARCH_TAG)"

if [[ -f "$APPIMAGE" ]] && [[ -z "$EXPECT_SHA" || "$(sha256sum "$APPIMAGE" | cut -d' ' -f1)" == "$EXPECT_SHA" ]]; then
    note "Already downloaded: $APPIMAGE"
else
    note "Downloading $URL"
    curl -fL --progress-bar -o "$APPIMAGE.part" "$URL" || die "Download failed."
    mv "$APPIMAGE.part" "$APPIMAGE"
    if [[ -n "$EXPECT_SHA" ]]; then
        GOT=$(sha256sum "$APPIMAGE" | cut -d' ' -f1)
        [[ "$GOT" == "$EXPECT_SHA" ]] || {
            rm -f "$APPIMAGE"
            die "Checksum mismatch. Expected $EXPECT_SHA, got $GOT."
        }
        note "Checksum verified."
    else
        note "Unpinned version: skipping the checksum check."
    fi
fi
chmod +x "$APPIMAGE"

# --------------------------------------------------------- 2. native or container
# The AppImage bundles its own Qt but still links the host's glibc. A release
# built on Ubuntu 24.04 needs glibc 2.38 and will not start on 22.04 (2.35),
# so read what the payload actually demands rather than guessing from the
# distro version.
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
( cd "$WORK" && "$APPIMAGE" --appimage-extract >/dev/null 2>&1 ) \
    || die "Could not unpack the AppImage. Is it a complete download?"
ROOT="$WORK/squashfs-root"

max_glibc() {
    # awk rather than "sort | tail -1": tail closes the pipe as soon as it has
    # its line, and under pipefail that SIGPIPE kills the whole script. Whether
    # it happens depends on how fast grep gets through 200MB of libraries, so
    # it fails intermittently. awk reads to the end and never closes early.
    { grep -aoh 'GLIBC_2\.[0-9]\{1,\}' "$ROOT/usr/bin/QGroundControl" "$ROOT"/usr/lib/*.so* 2>/dev/null \
        || true; } | sed 's/GLIBC_2\.//' | awk '$0 > m { m = $0 } END { print m + 0 }'
}
NEED_MINOR=$(max_glibc)
# getconf answers in one shot: "glibc 2.35". Deliberately not a pipeline - see
# the note in max_glibc about head/tail closing pipes under pipefail.
HOST_GLIBC=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)
[[ -z "$HOST_GLIBC" ]] && HOST_GLIBC=$(ldd --version 2>/dev/null || true)
[[ $HOST_GLIBC =~ 2\.([0-9]+) ]] && HOST_MINOR="${BASH_REMATCH[1]}" || HOST_MINOR=0
: "${NEED_MINOR:=0}"

if [[ "$MODE" == auto ]]; then
    if (( NEED_MINOR > HOST_MINOR )); then
        MODE=container
        say "Host glibc is 2.$HOST_MINOR; this build needs 2.$NEED_MINOR"
        note "Installing the containerised runtime instead of a native AppImage."
    else
        MODE=native
        say "Host glibc is 2.$HOST_MINOR; this build needs 2.$NEED_MINOR"
        note "Installing natively."
    fi
fi

# ------------------------------------------------------------------- 3. host deps
if (( DO_APT )); then
    if [[ "$MODE" == native ]]; then
        PKGS=(curl libfuse2 libxcb-xinerama0 libxkbcommon-x11-0 libxcb-cursor0
              gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl)
    else
        PKGS=(curl x11-xserver-utils)   # xauth, for handing X11 to the container
    fi
    MISSING=()
    for p in "${PKGS[@]}"; do
        dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
    done
    if (( ${#MISSING[@]} )); then
        say "Installing host packages (sudo)"
        note "${MISSING[*]}"
        sudo apt-get update -qq
        sudo apt-get install -y "${MISSING[@]}"
    fi
    # Serial access for USB radios and autopilots, and keep ModemManager's
    # hands off the Pixhawk, which it otherwise probes as a modem.
    if [[ " $(id -nG) " != *" dialout "* ]]; then
        say "Adding $(id -un) to the dialout group (sudo)"
        sudo usermod -aG dialout "$(id -un)"
        note "Log out and back in for this to take effect."
    fi
    MM_STATE=$(systemctl is-enabled ModemManager.service 2>/dev/null || true)
    if [[ -n "$MM_STATE" && "$MM_STATE" != masked ]]; then
        say "Masking ModemManager (sudo), which grabs USB serial autopilots"
        sudo systemctl mask --now ModemManager.service || true
    fi
fi

# -------------------------------------------------------------------- 4. install
if [[ "$MODE" == native ]]; then
    say "Installing $TARGET_BIN"
    install -m 755 "$APPIMAGE" "$TARGET_BIN"
else
    command -v docker >/dev/null || die "Docker is not installed. Install it, or re-run with --mode native."
    docker info >/dev/null 2>&1 || die "Cannot talk to the Docker daemon. Is it running, and are you in the docker group?"

    if (( REBUILD )) || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        say "Building $IMAGE"
        note "First build pulls ubuntu:24.04 and takes a few minutes."
        # Build context is a directory holding exactly one AppImage, so a
        # cache with several versions in it does not get sent to the daemon.
        CTX="$CACHE/ctx-${QGC_VERSION}-${ARCH_TAG}"
        rm -rf "$CTX" && mkdir -p "$CTX"
        ln -f "$APPIMAGE" "$CTX/$APPIMAGE_NAME" 2>/dev/null \
            || cp "$APPIMAGE" "$CTX/$APPIMAGE_NAME"
        docker build \
            -f "$HERE/Dockerfile" \
            --build-arg HOST_UID="$(id -u)" \
            --build-arg HOST_GID="$(id -g)" \
            --build-arg HOST_USER="$(id -un)" \
            --build-arg APPIMAGE="$APPIMAGE_NAME" \
            -t "$IMAGE" "$CTX"
        rm -rf "$CTX"
    else
        note "Image $IMAGE already built (--rebuild to force)."
    fi

    say "Installing $TARGET_BIN"
    sed -e "s|@VERSION@|${QGC_VERSION}|g" -e "s|@IMAGE@|${IMAGE}|g" \
        "$HERE/launcher.sh" > "$TARGET_BIN"
    chmod 755 "$TARGET_BIN"
fi

ln -sfn "$TARGET_BIN" "$BIN_DIR/qgroundcontrol"
note "qgroundcontrol -> v${QGC_VERSION}"

# -------------------------------------------------------------------- 5. settings
say "Settings"
mkdir -p "$CONFIG_DIR" "$HOME/Documents/QGroundControl" "$HOME/.cache/QGCMapCache300"
INI="$CONFIG_DIR/QGroundControl.ini"
if [[ -f "$INI" && $FORCE_SETTINGS -eq 0 ]]; then
    note "Keeping your existing $INI"
    note "(--force-settings replaces it with this repo's defaults)"
else
    if [[ -f "$INI" ]]; then
        BACKUP="$INI.$(date +%Y%m%d-%H%M%S).bak"
        cp -a "$INI" "$BACKUP"
        note "Backed up your old settings to $BACKUP"
    fi
    sed "s|@HOME@|$HOME|g" "$HERE/QGroundControl.ini" > "$INI"
    note "Installed defaults from local/qgc/QGroundControl.ini"
fi

# ------------------------------------------------------------ 6. desktop app
say "Desktop app"
# 5.1+ ships an SVG icon, 5.0 and earlier a PNG; the AppImage's .DirIcon points
# at whichever it is. The repo PNG is the fallback for a build carrying neither.
ICON_SRC=$(readlink -f "$ROOT/.DirIcon" 2>/dev/null || true)
if [[ ! -f "$ICON_SRC" ]]; then
    ICON_SRC=$(find "$ROOT" \( -iname '*qgroundcontrol*.svg' -o -iname '*qgroundcontrol*.png' \) \
        2>/dev/null | sort | awk '{ last = $0 } END { print last }')
fi
[[ -f "$ICON_SRC" ]] || ICON_SRC="$HERE/qgroundcontrol.png"
ICON_PATH="$ICON_DIR/qgroundcontrol-v${QGC_VERSION}.${ICON_SRC##*.}"
cp "$ICON_SRC" "$ICON_PATH"
note "Icon: $ICON_PATH"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=QGC ${QGC_VERSION}
Comment=Ground control station for drones
Exec=${TARGET_BIN}
Icon=${ICON_PATH}
Type=Application
Categories=Utility
Terminal=false
EOF
chmod +x "$DESKTOP_FILE"
note "Entry: $DESKTOP_FILE"

# Reload the launcher so the new app shows up without a log out. GNOME Shell
# rescans on its own once the database is rewritten; the touch is what makes it
# notice a file it has seen before.
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
touch "$DESKTOP_DIR"
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 || true
fi
note "Launcher reloaded."

# ------------------------------------------------------------------- 7. done
say "Ready"
note "Search your apps for \"QGC ${QGC_VERSION}\", or run: qgroundcontrol"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) note "Note: $BIN_DIR is not on your PATH. The desktop entry works regardless." ;;
esac
