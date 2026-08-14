#!/usr/bin/env bash
set -e

# Must resolve to the same interfaces share-on.sh used, or the rules stay behind.
: "${WIFI:=$(ip -o route show default | awk '{print $5; exit}')}"
: "${ETH:=$(ip -o -4 addr show | awk '/10\.200\.142\./ {print $2; exit}')}"

if [[ -z "$ETH" || -z "$WIFI" ]]; then
    echo "Could not detect interfaces (ETH='$ETH' WIFI='$WIFI')." >&2
    echo "Export ETH= and WIFI= and re-run." >&2
    exit 1
fi

sudo iptables -D FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
sudo iptables -t nat -D POSTROUTING -o "$WIFI" -j MASQUERADE 2>/dev/null || true

sudo sysctl -w net.ipv4.ip_forward=0 >/dev/null

echo "Internet sharing disabled."
