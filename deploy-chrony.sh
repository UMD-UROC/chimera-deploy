#!/usr/bin/env bash
# UNTESTED: standalone timing deployment for an aircraft. Merge into deploy.sh
# only after it has been confirmed through a hard power cycle.
set -euo pipefail

TIME_HOST=${TIME_HOST:-10.200.142.60}
FALLBACK_TIMEZONE=${FALLBACK_TIMEZONE:-America/New_York}
CHRONY_CONF=/etc/chrony/chrony.conf
CHRONY_SOURCE="server ${TIME_HOST} iburst prefer minpoll 4 maxpoll 4 minsamples 1 maxsamples 4"

# Match the host timezone when SSH is available; retain a known-safe fallback
# for an aircraft that has the time network but no SSH credentials yet.
TIMEZONE=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "${TIME_HOST}" \
  'timedatectl show --property=Timezone --value' 2>/dev/null || true)
TIMEZONE=${TIMEZONE:-$FALLBACK_TIMEZONE}
sudo timedatectl set-timezone "$TIMEZONE"

sudo install -d -m 755 /etc/chrony/sources.d
# Replace the earlier deploy.sh source line if it is present, so the preferred
# fast-poll source below is the only definition for this host.
sudo sed -i "\\|^server ${TIME_HOST} iburst$|d" "$CHRONY_CONF"
printf '%s\n' "$CHRONY_SOURCE" | sudo tee /etc/chrony/sources.d/chimera-host.sources >/dev/null

# Step large RTC errors at every start, then poll the low-latency host every
# 16 seconds. Public pools in chrony.conf remain as fallbacks.
sudo sed -i 's/^makestep 1 3$/makestep 1 -1/' "$CHRONY_CONF"
sudo install -d -m 755 /etc/systemd/system/chrony.service.d
sudo tee /etc/systemd/system/chrony.service.d/chimera-network.conf >/dev/null <<'EOF'
[Unit]
Wants=network-online.target
After=network-online.target
EOF
sudo systemctl daemon-reload
sudo systemctl restart chrony

echo "Timezone: $(timedatectl show --property=Timezone --value)"
chronyc tracking
chronyc sources -v
