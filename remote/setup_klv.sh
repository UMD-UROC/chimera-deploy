#!/bin/bash
# Installs the KLV geolocation responder as a service and restarts rcam so it
# picks up the rgblk mount. Run on the drone.
set -e

cd "$(dirname "$0")"

sudo cp klv.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable klv.service
sudo systemctl restart klv.service
sudo systemctl restart rcam.service

systemctl --no-pager --lines=5 status klv.service rcam.service || true
