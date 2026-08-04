#!/usr/bin/env bash
set -e

ETH=enp132s0
WIFI=wlp129s0f0

sudo iptables -D FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
sudo iptables -t nat -D POSTROUTING -o "$WIFI" -j MASQUERADE 2>/dev/null || true

sudo sysctl -w net.ipv4.ip_forward=0 >/dev/null

echo "Internet sharing disabled."
