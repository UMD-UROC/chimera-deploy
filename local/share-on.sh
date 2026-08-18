#!/usr/bin/env bash
set -e

# ETH faces the drones, WIFI faces the internet. Both are detected from the
# routing table so this works on any laptop; override by exporting either name.
: "${WIFI:=$(ip -o route show default | awk '{print $5; exit}')}"
: "${ETH:=$(ip -o -4 addr show | awk '/10\.200\.142\./ {print $2; exit}')}"

if [[ -z "$ETH" || -z "$WIFI" ]]; then
    echo "Could not detect interfaces (ETH='$ETH' WIFI='$WIFI')." >&2
    echo "Export ETH= and WIFI= and re-run." >&2
    exit 1
fi

echo "Sharing $WIFI -> $ETH"

sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

sudo iptables -C FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT 2>/dev/null || \
sudo iptables -A FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT

sudo iptables -C FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
sudo iptables -A FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

sudo iptables -t nat -C POSTROUTING -o "$WIFI" -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING -o "$WIFI" -j MASQUERADE

echo "Internet sharing enabled."
echo "On the drone: sudo ip route add default via 10.200.142.60"
