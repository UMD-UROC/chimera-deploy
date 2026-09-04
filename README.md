# Overview

In it's current status, the Chimera setup/flashing/deploy is split into three processes across two scripts and a NVIDIA tool. The steps are described below and will be improved over time. The current set of instructions has been tested on a physical Ubuntu 22.04 LTS machine as of 2025-10-20.

Note: there may be untracked packages on the host machine not captured in this setup. Please add any needed to this README.

# Setup/Flashing Instructions

Download this repo onto your machine and navigate to it. Then execute ```DRONE_PASSWORD=<the drone password> ./setup.sh``` to download the necessary files from nvidia and apply the custom echopilot board support package. This prepares the files required for flashing the Orin. The password is in the team password store and this repository does not carry it. The script sets the drone's `user` account to it and refuses to run without it.

UAS number should correspond to the mavlink system ID of the intended drone. If you have one drone, setting to 1 is a safe bet. If you're using multiple drones, you should set different mavlink system IDs for each aircraft. Use the same number for the deploy script later for each drone.

The flashing process the Orin to be in recovery mode and the micro usb to be plugged into the Jetson debug port

1. Ensure Orin is off
2. Hold "RCVRY" button and apply power
3. Wait 5s
4. Plug in the micro-usb into the Jetson DEBUG port (not the usb-c Jetson console)

Then run the command ```cd $HOME/Orin/Linux_for_Tegra/; sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_external.xml -p "-c bootloader/generic/cfg/flash_t234_qspi.xml --no-systemimg" --network usb0 echopilot-ai external``` to flash the board. This process takes ~15mins.

Once complete, power cycle the Orin and remove the micro-usb debug cable.

# NVIDIA SDK Install

Plug in the usb-c console cable. Also connect the ethernet cable to your router in order to get internet to make the deploy process easier.

To install the NVIDIA SDK, the NVIDIA SDK Manager can be used (download from nvidia https://developer.nvidia.com/sdk-manager). Before going to the sdk manager, we need some information from the Orin:

## Set up SSH and get IP for NVIDIA SDK step
### host
Note: may need to explicity define the /dev/ttyUSB# number corresponding to the Orin, works best when the Orin is the only ttyUSB device connected to your host computer
```picocom /dev/ttyUSB? -b 115200 # connect to orin```

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
password: # the drone password, from the team password store
target proxy settings: do not set proxy
install

This process takes ~30mins, once complete move on to the deploy steps

# Chimera SDK Install

Now all that's left is to install the chimera SDK. Since we have the git repo cloned already, all we need to do is ssh into the drone, go to the repo, and execute the deploy script

### host
```ssh user@<IP>```

### orin
```cd chimera-deploy; ./deploy.sh```
Be sure to use the correct UAS number from earlier

`deploy.sh` writes `UAS_NUM` and `ROS_DOMAIN_ID` into `/etc/environment`,
installs the native services, and then calls `remote/deploy_onboard.sh`, which
puts the onboard container on the aircraft. The next section says what that
step does.

Finally, I recommend using ```sudo nmtui``` to configure the network connections. You will need to reboot or unplug and replug the wifi adapter after flashing to initialize it. You will also likely need to redo the ssh key to allow your host to connect to the Orin if you don't always use the ethernet hardwired to your router.

CUDA
```
sudo apt update
sudo apt upgrade
sudo ubuntu-drivers autoinstall # for cuda/nvidia-smi
```
Local Cam Server
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
Aliases
```
cp local/.bash_aliases ~/.bash_aliases
source ~/.bash_aliases
```
MAVLink Router
```
sudo cp local/main.conf /etc/mavlink-router/main.conf
sudo systemctl restart mavlink-router
sudo systemctl status mavlink-router
```

# Onboard container on the aircraft

The flight code runs on the aircraft in a container, from the px4-sim-stack
`aircraft` profile. One image carries MAVROS, `ds_node`, the gimbal and zoom
nodes and the MAVInsight frame tree, and the native `rcam.service` and
`mavlink-router.service` keep serving the cameras and the autopilot beside it.

`remote/deploy_onboard.sh` puts it in place. Run it on the Orin as `user`, from
this directory, after `deploy.sh` or on its own:

```
./remote/deploy_onboard.sh                     # install the boot unit, do not enable it
ENABLE_BOOT_UNIT=1 ./remote/deploy_onboard.sh  # and enable it
```

Each step examines the machine before it acts, so a second run changes nothing.
It adds `user` to group `docker`, renames `~/ros2_ws/src/umd_uas` to
`~/ros2_ws/src/5g_drone`, clones px4-sim-stack from the laptop's git daemon,
writes its `.env` with the aircraft keys and the SCF4 lens path, links this
machine's TensorRT engines with `fetch_models.py resolve --link`, and installs
`remote/onboard.service`.

**The flight code directory is `5g_drone`, not `umd_uas`.** The container build
and `fetch_models.py` both read that name. `setup_git_server.sh remote` and
`remote/deploy_onboard.sh` each move an old checkout rather than clone a second
one, because two directories of one ROS package stop the colcon build.

`remote/onboard.service` starts the stack at boot:

```
sudo systemctl enable --now onboard
sudo systemctl restart onboard        # after a rebuild
journalctl -u onboard -n 40
```

It is a `oneshot` unit, ordered after `docker.service`, `rcam.service`,
`mavlink-router.service` and `time-sync.target`. It removes any container a
power cut left, waits up to three minutes for a clock step with
`chronyc waitsync`, then runs `px4sim start`. `SupplementaryGroups=docker`
gives it the docker socket whether or not the login user is in that group.

`remote/.bash_aliases` holds the hand versions. Copy it to `~/.bash_aliases` on
the Orin:

```
onboard         # cd ~/px4-sim-stack && ./px4sim start
onboard-logs    # cd ~/px4-sim-stack && ./px4sim logs onboard
onboard-native  # the same launch with no container, for a machine with no image
```

The container is the path this aircraft flies. `onboard-native` and the older
`uspi<N>` aliases start the same launch natively, and they are for a machine
that has no image yet. Never run a native launch and the container at once: one
MAVROS can bind 14402, and one node can hold the SCF4 lens.

Everything after the deploy goes through the px4-sim-stack front door, and
`px4-sim-stack/docs/front-doors.md` is the guide to it. It carries the command
line for the aircraft, for the ground station on the base station laptop and
for the simulator, and it says what each door reads and what it refuses. It
also covers `setup_git_server.sh`, which is how code reaches a drone that
cannot reach GitHub.

# QGroundControl

```
./local/qgc/quickstart.sh
```

One command from a clean machine to a launchable app: it downloads and
checksums a pinned release, installs the runtime packages, grants serial
access, seeds the flight-tested settings from `local/qgc/QGroundControl.ini` if
you have none of your own, and registers a desktop entry named `QGC <version>`.
Re-running it is safe and never overwrites settings you already have.

On Ubuntu 22.04 it installs a containerised runtime automatically: the v5.1
AppImages are built on Ubuntu 24.04 and need glibc 2.38, which 22.04 does not
have. The container holds no state, so settings, logs, map tiles, the network
stack and `/dev` stay on the host either way.

Nothing is precious: `--uninstall` removes the app, icon, entry, image and
download in one go, and re-running the script rebuilds all of it. The container
image can also be built on its own with plain `docker build` - it fetches the
release from GitHub Releases and verifies the checksum itself, so no binary
lives in this repo.

See [`local/qgc/README.md`](local/qgc/README.md) for the options, rebuilding,
and how to bump the pinned version.
