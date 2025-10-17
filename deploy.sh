# git repo
git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
cd chimera-deploy


# wifi drivers
sudo apt update
sudo apt install linux-headers-generic build-essential git
cd submodules/rtw88
make
sudo make install
sudo make install_fw
cd ../..
# reboot and then use nmtui to configure wifi before it will work

# echotherm daemon (thermal cam setup)
cd submodules/EchoTherm-Daemon
sudo ./install.sh
echothermd --daemon
cd ../..

# imx477 setup
sudo cp remote/board.py /opt/nvidia/jetson-io/Jetson/board.py
sudo /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Camera IMX477 Custom Echopilot Overlay"
# need to reboot before it will work

# rtsp server
sudo apt install -y gir1.2-gst-rtsp-server-1.0 python3-gi
cp remote/multi_rtsp_server.py ~

# echomav deploy
cd submodules/echopilot_deploy/
./deploy.sh no-static
cd ../..





## mavlink router
# modify endpoint alpha to go to base station ip line 49 from Address = 10.223.1.10 > 10.200.91.50
# make individual ports match 1455X where X is drone number, make sure this is applied to all the drones AND the base station
# make sure to add "AllowSrcSysIn = X,255" under the drone udp endpoints where X is drone number
#!/bin/bash
UAS_NUM=3  # or set dynamically
echo "UAS_NUM=${UAS_NUM}" | sudo tee -a /etc/environment
source /etc/environment
envsubst < ./remote/main.conf.template | sudo tee /etc/mavlink-router/main.conf

sudo systemctl enable mavlink-router.service
sudo systemctl restart mavlink-router.service

# use nmtui to configure the network appropriately
# we use 10.200.91.5x/24 where x = drone number for our drones for roboscout
# be sure to set gcs to 10.200.91.50 (or whatever mavlink router endpoint alpha is set to)
nmtui
# make sure interfaces are correct! d3 is weird, may have done something wrong
sudo cp /home/j1/*.nmconnection /etc/NetworkManager/system-connections/
sudo nmcli connection load /etc/NetworkManager/system-connections/*
sudo systemctl restart NetworkManager
sudo nmtui
