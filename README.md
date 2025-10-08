## flash setup
# download source
cd ~/Downloads
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/Jetson_Linux_r36.4.4_aarch64.tbz2
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/sources/public_sources.tbz2

mkdir -p ~/Orin
tar xpf ~/Downloads/Jetson_Linux_r36.4.4_aarch64.tbz2 -C ~/Orin

sudo tar xpf ~/Downloads/Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2 -C ~/Orin/Linux_for_Tegra/rootfs/
cd ~/Orin/Linux_for_Tegra
sudo ./apply_binaries.sh

sudo tools/l4t_create_default_user.sh -u user -p oelinux123 -n chimera-d3-orin --accept-license

cd ~
git clone https://github.com/EchoMAV/echopilot_ai_bsp
cd echopilot_ai_bsp

git checkout board_revision_1b

sudo ./install_l4t_orin.sh ~/Orin/Linux_for_Tegra/


## flash

# plug in micro usb and hold recovery button

cd ~/Orin/Linux_for_Tegra/
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_external.xml -p "-c bootloader/generic/cfg/flash_t234_qspi.xml --no-systemimg" --network usb0 echopilot-ai external

## power cycle and plug in ethernet to router

picocom /dev/ttyUSB? -b 115200

ifconfig # to get ip

# orin
sudo ssh-keygen -A
sudo systemctl restart ssh

# host
ssh-keygen -t rsa -b 4096
ssh-copy-id -i ~/.ssh/id_rsa.pub user@192.168.1.6


### sdk manager app (download from nvidia https://developer.nvidia.com/sdk-manager)
## host
# step 01
product category: jetson
system config: jetson orin nx 16gb
sdk version: jetpack 6.2.1 rev1
aditional sdks: deepstream, gtk
next

# step 02
UNCHECK Jetson Linux # we DONT want to flash
check everything else
accept terms
next

# step 03
connection: ethernet
ip address: ipv4 192.168.1.XXX # check recorded ip from wifi setup step
username: user
password: oelinux123
target proxy settings: do not set proxy
install

### wifi
## orin
# setup drivers (and other rtw88XX based modules https://github.com/lwfinger/rtw88)
sudo apt update && sudo apt upgrade -y
sudo apt install -y linux-headers-$(uname -r) build-essential git
cd
git clone https://github.com/lwfinger/rtw88
cd rtw88
make
sudo make install
sudo make install_fw
# unplug and replug wifi adapter, should be ready to connect to wifi in ~30s

sudo nmtui # set up wifi using nmtui and activate it

### install echotherm drivers (https://echomav.github.io/echotherm_docs/latest/quickstart/)
## orin
# prereqs
sudo apt update
sudo apt install -y git-all build-essential
# clone repo
git clone https://github.com/EchoMAV/EchoTherm-Daemon.git
cd EchoTherm-Daemon
sudo ./install.sh

# reboot
sudo reboot

# start daemon
echothermd --daemon # should hear clicking noises

# kill daemon
echothermd --kill # kills daemon

## imx477
# https://github.com/EchoMAV/Camera_Modules/tree/main#
sudo vi /boot/extlinux/extlinux.conf
# add these
      FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
      OVERLAYS /boot/tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo
# host
git clone git@github.com:EchoMAV/Camera_Modules.git
cd Camera_Modules
scp tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo user@192.168.1.38:/home/user
# orin
sudo cp tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo /boot
sudo /opt/nvidia/jetson-io/config-by-hardware.py # 24 pin csi, echomav imx477

sudo reboot

# push rtsp server
scp ~/DTC/chimera-recording-visualization/multi_rtsp_server.py user@192.168.1.38:/home/user

# echomav deploy
git clone https://github.com/echomav/echopilot_deploy.git /tmp/echopilot_deploy && cd /tmp/echopilot_deploy
./deploy.sh no-static

## mavlink router
# modify endpoint alpha to go to base station ip line 49 from Address = 10.223.1.10 > 10.200.91.50
# make individual ports match 1455X where X is drone number, make sure this is applied to all the drones AND the base station
# make sure to add "AllowSrcSysIn = X,255" under the drone udp endpoints where X is drone number
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


# (optional once implemented) copy network manager connections into uav and gcs and modify the device names

## gimbal notes
# go to encoders panel
# set the encoder el field values to zero (uncalibrated)
# hold gimbal level and calibrate offsets
# reboot if needed and gimbal should be relatively level (but red bars should be visible next to the angles)
# do the el field calibration
# now the red bars should all be tiny
# UPDATE MAVLINK SYSTEM ID TO MATCH (need to do this for the px4 sys id, px4 mnt sys id, and gimbal ext imu system id)







