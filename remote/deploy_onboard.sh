#!/usr/bin/env bash
# Prepare the onboard container configuration after the host sync has placed
# the flight repositories and px4-sim-stack. Each step examines
# the machine before it acts, so a second run changes nothing.
#
# Run it on the Orin as `user`, from ~/chimera-deploy, after deploy.sh or on
# its own. Repository distribution is owned by the host sync front door:
# `cd ~/chimera-deploy && ./sync_ui.py sync`. Start or restart the aircraft
# only through ./px4sim.
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK=$HOME/px4-sim-stack
WS=${WS:-$HOME/ros2_ws}

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
die() { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

# Use the same writer and identity resolver as sync and the camera server.
set_env_key() {
  python3 "$DEPLOY_ROOT/remote/aircraft_config.py" --update-env "$1" "$2" "$3" >/dev/null
}
ensure_env_key() {
  grep -q "^$2=" "$1" || set_env_key "$1" "$2" "$3"
}
identity=$(python3 "$DEPLOY_ROOT/remote/aircraft_config.py" --identity) || exit 1
eval "$identity"
ROS_DOMAIN_ID=$((60 + UAS_NUM))
me=$(id -un)

say "preflight"
[ -d "$WS/src/5g_drone" ] || die "$WS/src/5g_drone is missing. Run the host sync command first: cd ~/chimera-deploy && ./sync_ui.py sync"

say "docker group"
sudo bash "$(dirname -- "${BASH_SOURCE[0]}")/install_encoder_udev.sh"
if id -nG "$me" | grep -qw docker; then
  echo "  $me is in docker"
else
  sudo usermod -aG docker "$me"
  echo "  added $me to docker. Log in again before ./px4sim runs without sudo."
fi

say "flight code directory name"
if [ -d "$WS/src/umd_uas" ] && [ ! -e "$WS/src/5g_drone" ]; then
  mv "$WS/src/umd_uas" "$WS/src/5g_drone"
  echo "  renamed umd_uas to 5g_drone"
fi
[ -d "$WS/src/5g_drone" ] || die "$WS/src/5g_drone is missing. Run ./setup_git_server.sh remote on this machine
  (from the laptop: ./setup_git_server.sh deploy). It also brings cdcl_umd_msgs, MAVInsight and px4_msgs,
  which the container build needs."

say "px4-sim-stack at $STACK"
[ -d "$STACK/.git" ] || die "$STACK is missing. Run the host sync command first: cd ~/chimera-deploy && ./sync_ui.py sync"
# The log volumes bind here. Docker makes a missing one root-owned, and the
# uid 1000 container then writes nothing into it.
mkdir -p "$STACK"/logs/{onboard,offboard,px4,qgc}

say ".env"
lens=
for dev in /dev/serial/by-id/usb-Kurokesu_*; do
  [ -e "$dev" ] && { lens=$dev; break; }
done
if [ ! -f "$STACK/.env" ]; then
  cp "$STACK/.env.example" "$STACK/.env"
  printf '\n# The aircraft. Written by chimera-deploy/remote/deploy_onboard.sh.\n' >> "$STACK/.env"
  set_env_key "$STACK/.env" COMPOSE_PROFILES aircraft
  set_env_key "$STACK/.env" UAS_BASE 0
  set_env_key "$STACK/.env" UAS_FLEET 'chimera_v3 chimera_v3 chimera_v2 chimera_v2'
  set_env_key "$STACK/.env" SCENE ''
  set_env_key "$STACK/.env" SCENARIO ''
  set_env_key "$STACK/.env" SIMNET_PREFIX 172.28.0
  set_env_key "$STACK/.env" ONBOARD_LENS_DEVICE "$lens"
  # The host's own ids. `px4sim start` does not read the host the way
  # `px4sim doctor` does.
  set_env_key "$STACK/.env" HOST_UID "$(id -u)"
  set_env_key "$STACK/.env" HOST_GID "$(id -g)"
  render_gid=$(getent group render | cut -d: -f3 || true)
  if [ -n "$render_gid" ]; then
    set_env_key "$STACK/.env" RENDER_GID "$render_gid"
  fi
  echo "  wrote $STACK/.env for uas$UAS_NUM"
else
  sed -i '/^ROS_DOMAIN_ID=/d' "$STACK/.env"
  echo "  $STACK/.env exists; set UAS_NUM=$UAS_NUM UAS_MODEL=$UAS_MODEL"
fi
python3 "$DEPLOY_ROOT/remote/aircraft_config.py" --update-env "$STACK/.env" --repair-identity >/dev/null
# New .env.example files already contain these selectors. Seed older aircraft
# configurations as well, while preserving choices pushed by the ground UI.
ensure_env_key "$STACK/.env" UAS_ROLES 'assess assess search search'
ensure_env_key "$STACK/.env" CONOPS option1
if [ -n "$lens" ] && ! grep -qxF "ONBOARD_LENS_DEVICE=$lens" "$STACK/.env"; then
  echo "  the SCF4 is $lens and .env says: $(grep '^ONBOARD_LENS_DEVICE=' "$STACK/.env" || echo nothing)"
fi

say "model links"
ORIN_PARAMS="$WS/src/5g_drone/perception_models/orin/params.yaml"
if [ ! -f "$ORIN_PARAMS" ] || ! grep -q 'model.detector: "yolo12l-custom-960"' "$ORIN_PARAMS"; then
  install -m 644 "$DEPLOY_ROOT/remote/orin_params.yaml" "$ORIN_PARAMS"
  echo "  wrote the Orin detector override: yolo12l-custom-960"
else
  echo "  keeping existing $ORIN_PARAMS"
fi
"$WS/src/5g_drone/scripts/fetch_models.py" resolve --link ||
  die "fetch_models.py knows no engine group for this machine. Add a rule for it to $WS/src/5g_drone/perception_models/manifest.json, then run this again."
"$WS/src/5g_drone/scripts/fetch_models.py" check --role onboard || true

say "next"
echo "  cd $STACK && ./px4sim doctor && ./px4sim restart aircraft"
