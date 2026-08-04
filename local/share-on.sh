#!/usr/bin/env bash
set -e

ETH=enp132s0
WIFI=wlp129s0f0

sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

sudo iptables -C FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT 2>/dev/null || \
sudo iptables -A FORWARD -i "$ETH" -o "$WIFI" -j ACCEPT

sudo iptables -C FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
sudo iptables -A FORWARD -i "$WIFI" -o "$ETH" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

sudo iptables -t nat -C POSTROUTING -o "$WIFI" -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING -o "$WIFI" -j MASQUERADE

echo "Internet sharing enabled."
