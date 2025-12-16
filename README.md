# Overview

In it's current status, the Chimera setup/flashing/deploy is split into three processes across two scripts and a NVIDIA tool. The steps are described below and will be improved over time. The current set of instructions has been tested on a physical Ubuntu 22.04 LTS machine as of 2025-10-20.

Note: there may be untracked packages on the host machine not captured in this setup. Please add any needed to this README.

# Setup/Flashing Instructions

Download this repo onto your machine and navigate to it. Then execute ```./setup.sh``` to download the necessary files from nvidia and apply the custom echopilot board support package. This prepares the files required for flashing the Orin.

UAS number should correspond to the mavlink system ID of the intended drone. If you have one drone, setting to 1 is a safe bet. If you're using multiple drones, you should set different mavlink system IDs for each aircraft. Use the same number for the deploy script later for each drone.

The flashing process the Orin to be in recovery mode and the micro usb to be plugged into the Jetson debug port

1. Ensure Orin is off
2. Hold "RCVRY" button and apply power
3. Wait 5s
4. Plug in the micro-usb into the Jetson DEBUG port (not the usb-c Jetson console)

Then run the command 
```
cd $HOME/Orin/Linux_for_Tegra/ && sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_external.xml -p "-c bootloader/generic/cfg/flash_t234_qspi.xml --no-systemimg" --network usb0 echopilot-ai external
```
to flash the board. This process takes ~15mins.

Once complete, power cycle the Orin and remove the micro-usb debug cable.

# NVIDIA SDK Install

Plug in the usb-c console cable. Also connect the ethernet cable to your router in order to get internet to make the deploy process easier.

To install the NVIDIA SDK, the NVIDIA SDK Manager can be used (download from nvidia https://developer.nvidia.com/sdk-manager). Before going to the sdk manager, we need some information from the Orin:

## Set up SSH and get IP for NVIDIA SDK step
### host
Note: may need to explicity define the /dev/ttyUSB# number corresponding to the Orin, works best when the Orin is the only ttyUSB device connected to your host computer
```
picocom /dev/ttyUSB? -b 115200 # connect to orin
```

### orin
```
ifconfig # to get ip of the orin on your network
sudo ssh-keygen -A # generate ssh key to enable ssh
sudo systemctl restart ssh # 
```

### host
```
ssh-keygen -t rsa -b 4096 # unless already exists
ssh-copy-id -i $HOME/.ssh/id_rsa.pub user@192.168.1.220 # replace ip with ip for your machine
```
Now you can ssh into your drone with ```ssh user@<IP>```

## Set up Git on Orin and clone this repo
### orin
```
ssh-keygen -t rsa -b 4096
cat /home/user/.ssh/id_rsa.pub # add this to your github account ssh keys
```
```
git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
cd chimera-deploy
git submodule update --init --recursive # to update submodules
```
This can be done after the NVIDIA SDK install, I just prefer to set up everything at the same time

## NVIDIA SDK Manager
### host
1. step 01
product category: jetson
system config: jetson orin nx 16gb
sdk version: jetpack 6.2.1 rev1
aditional sdks: deepstream, gtk
next

2. step 02
UNCHECK Jetson Linux # we DONT want to flash, if you check this you will need to redo everything up until this point!
check everything else
accept terms
next

3. step 03
connection: ethernet
ip address: ipv4 192.168.1.XXX # check recorded ip from wifi setup step
username: user
password: Talon240
target proxy settings: do not set proxy
install

This process takes ~30mins, once complete move on to the deploy steps

# Chimera SDK Install

Now all that's left is to install the chimera SDK. Since we have the git repo cloned already, all we need to do is ssh into the drone, go to the repo, and execute the deploy script

### host
```
ssh user@<IP>
```

### orin
```
cd ~/chimera-deploy && ./deploy.sh
```
Be sure to use the correct UAS number from earlier

Finally, I recommend using 
```
sudo nmtui
```
to configure the network connections. You will need to reboot or unplug and replug the wifi adapter after flashing to initialize it. You will also likely need to redo the ssh key to allow your host to connect to the Orin if you don't always use the ethernet hardwired to your router.

```
sudo apt update
sudo apt upgrade
sudo ubuntu-drivers autoinstall # for cuda/nvidia-smi
```
```
open local/lcam.service # update path for your machine
```
```
sudo apt install gir1.2-gst-rtsp-server-1.0
sudo cp local/lcam.service /etc/systemd/system/lcam.service
sudo systemctl daemon-reload 
sudo systemctl enable lcam.service
sudo systemctl start lcam.service
sudo systemctl status lcam.service
```
```
cp local/.bash_aliases ~/.bash_aliases
source ~/.bash_aliases
```
