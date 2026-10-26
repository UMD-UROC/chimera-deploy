#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"
install -m 755 "$HERE/launcher.sh" "$BIN_DIR/foxglove-studio"
sed "s|@HOME@|$HOME|g" "$HERE/foxglove-studio.desktop" \
    > "$DESKTOP_DIR/foxglove-studio.desktop"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
