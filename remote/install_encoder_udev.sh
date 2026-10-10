#!/usr/bin/env bash
# Native host permissions only. Container launch stays behind px4sim restart.
set -euo pipefail
rule_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: $0" >&2
  exit 1
fi
install -m 0644 "$rule_dir/99-chimera-encoder.rules" /etc/udev/rules.d/99-chimera-encoder.rules
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=10c4 --attr-match=idProduct=ea60 --attr-match=serial=0001
udevadm trigger --action=change --subsystem-match=tty --sysname-match='ttyUSB*'
udevadm settle
echo 'Installed CP2102 encoder permissions for dialout; no EEPROM changes.'
