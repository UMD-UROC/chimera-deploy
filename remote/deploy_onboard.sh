#!/usr/bin/env bash
# Put the onboard container on an aircraft: docker access, the px4-sim-stack
# checkout, its .env, the model links and the boot unit. Each step examines
# the machine before it acts, so a second run changes nothing.
#
# Run it on the Orin as `user`, from ~/chimera-deploy, after deploy.sh or on
# its own. It needs git://10.200.142.60 (setup_git_server.sh local on the
# laptop). Enable the unit only after the bench tests: ENABLE_BOOT_UNIT=1.
set -euo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_IP=${SERVER_IP:-10.200.142.60}
GIT_PORT=${GIT_PORT:-9418}
STACK=${STACK:-$HOME/px4-sim-stack}
STACK_BRANCH=${STACK_BRANCH:-feature/real-drone-port}
WS=${WS:-$HOME/ros2_ws}

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }
die() { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

# set_env_key <file> <key> <value>: replace the key's line, or append one
set_env_key() {
  if grep -q "^$2=" "$1"; then
    sed -i "s|^$2=.*|$2=$3|" "$1"
  else
    echo "$2=$3" >> "$1"
  fi
}

UAS_NUM=$(sed -n 's/^UAS_NUM=//p' /etc/environment | tr -d '"' | tail -1)
[ -n "$UAS_NUM" ] || die "UAS_NUM is not in /etc/environment. Run deploy.sh first."
case "$UAS_NUM" in [1-9]) ;; *) die "UAS_NUM=$UAS_NUM is not 1 to 9" ;; esac
me=$(id -un)

say "docker group"
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
[ -d "$WS/src/5g_drone" ] || die "$WS/src/5g_drone is missing. Clone it from git://$SERVER_IP:$GIT_PORT/5g_drone.git"

say "px4-sim-stack at $STACK"
if [ ! -d "$STACK/.git" ]; then
  git clone --branch "$STACK_BRANCH" "git://$SERVER_IP:$GIT_PORT/px4-sim-stack.git" "$STACK"
fi

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
  set_env_key "$STACK/.env" UAS_FLEET '"chimera_v3 chimera_v3 chimera_v2 chimera_v2"'
  set_env_key "$STACK/.env" SCENE ''
  set_env_key "$STACK/.env" SCENARIO ''
  set_env_key "$STACK/.env" SIMNET_PREFIX 172.28.0
  set_env_key "$STACK/.env" ONBOARD_LENS_DEVICE "$lens"
  echo "  wrote $STACK/.env for uas$UAS_NUM"
else
  echo "  $STACK/.env exists, left as it is"
fi
if [ -n "$lens" ] && ! grep -qxF "ONBOARD_LENS_DEVICE=$lens" "$STACK/.env"; then
  echo "  the SCF4 is $lens and .env says: $(grep '^ONBOARD_LENS_DEVICE=' "$STACK/.env" || echo nothing)"
fi

say "model links"
"$WS/src/5g_drone/scripts/fetch_models.py" resolve --link
"$WS/src/5g_drone/scripts/fetch_models.py" check --role onboard || true

say "boot unit"
sudo install -m 644 "$DEPLOY_ROOT/remote/onboard.service" /etc/systemd/system/onboard.service
sudo systemctl daemon-reload
if [ "${ENABLE_BOOT_UNIT:-0}" = 1 ]; then
  sudo systemctl enable onboard.service
  echo "  onboard.service enabled. It starts at the next boot."
else
  echo "  onboard.service installed, not enabled. After the bench tests:"
  echo "    sudo systemctl enable --now onboard"
fi

say "next"
echo "  log in again, then:  cd $STACK && ./px4sim doctor && ./px4sim build && ./px4sim start"
