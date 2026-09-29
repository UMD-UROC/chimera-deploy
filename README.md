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

For Chimera v3 aircraft (UAS 1–2), the deploy script configures the wired
RoboScout interface (`10.200.142.62/24` for UAS 2) and does not install a Wi-Fi
module. Chimera v2 aircraft (UAS 3–4) take the legacy `rtw88` Wi-Fi-driver
path instead. When a v3 ground link is ready to share internet, run this on
the ground station (not on the drone):

```
cd chimera-deploy
./local/share-on.sh
```

Then, on the drone, add the shared-link default route:

```
sudo ip route replace default via 10.200.142.60 dev eno1
```

`deploy.sh` writes `UAS_NUM` and `ROS_DOMAIN_ID` into `/etc/environment`,
installs the native services, and then calls `remote/deploy_onboard.sh`, which
puts the onboard container on the aircraft. The next section says what that
step does.

Do not run `sudo apt upgrade` or `ubuntu-drivers autoinstall` as part of this
deployment. The SDK/JetPack versions are intentionally pinned. The deploy
script does not change the existing Wi-Fi connection and only adds the
RoboScout address on the connected wired interface.

For the intended split, the drone uses the PX4Sim `aircraft` profile and the
laptop uses the `ground` profile. The laptop runs `./px4sim ui` and the
`chimera_real` Foxglove layout; the drone runs only its `onboard` container
plus native camera/router services. The old broad EchoMAV installer and
pre-container ROS launch aliases are retained as legacy material and are not
needed for routine PX4Sim deployment.
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

The host `sync` front door distributes the flight repositories and
px4-sim-stack. Run this on the laptop first:

```
cd ~/chimera-deploy && ./sync_ui.py sync
```

Then `remote/deploy_onboard.sh` configures the already-synced aircraft
checkout. Run it on the Orin as `user`, from this directory:

```
./remote/deploy_onboard.sh                     # prepare the aircraft checkout and models
cd ~/px4-sim-stack && ./px4sim restart aircraft # build/start through the PX4Sim front door
```

Each step examines the machine before it acts, so a second run changes nothing.
It adds `user` to group `docker`, renames `~/ros2_ws/src/umd_uas` to
`~/ros2_ws/src/5g_drone`, and links this machine's TensorRT engines with
`fetch_models.py resolve --link`. Repository cloning and updates are owned by
the host sync command and are not duplicated here.
It does not install a systemd lifecycle unit; use `./px4sim start`, `./px4sim
restart`, `./px4sim stop`, and `./px4sim status` for stack lifecycle control.

**The flight code directory is `5g_drone`, not `umd_uas`.** The container build
The host sync command selects the branch and updates the aircraft checkout.
`remote/deploy_onboard.sh` only moves an old `umd_uas` directory into the
expected `5g_drone` name; it does not clone or update repositories.

The aircraft Compose service is controlled by the PX4Sim front door, not a
second systemd lifecycle path. This keeps stop, build, and start behavior in
one place.

`setup_git_server.sh sync` is the deployment front door. After uploading
repository updates, it invokes `./px4sim restart` on the ground station and every
reachable Orin. `px4sim restart` always performs stop, build, and start, so a
checkout cannot run with an older image. Cached builds are expected on every
sync; dirty or diverged worktrees are left untouched and reported. The sync also
reconciles `SCENE`, `SCENARIO`, `CONOPS`, `UAS_ROLES`, and `ONBOARD_CAMERA`
(day or night) from the ground station's px4-sim-stack `.env`, so an aircraft
that was offline when an operator changed a selector catches up when it
reconnects.
The foreground sync command reports `BUILDING`, `SUCCESS`, `FAILURE`, or
`UNREACHABLE` for the ground station and each aircraft while their full Docker
logs remain grouped.

## Deployment doctor

Run the read-only health check on an aircraft after deployment:

```
./remote/deploy_doctor.sh
```

It checks the airframe identity, RoboScout or v2 Wi-Fi path, native services,
PX4Sim container, ROS camera and MAVROS topics, detector engine, and the native
MAVLink UART/router. It exits nonzero for hard failures and reports warnings
separately. The thermal warning is intentional: on the current hardware the
Boson can stream successfully at startup, then disappear from USB after about
30 seconds when RGB, thermal, and gimbal traffic saturate the shared hub. The
doctor records that as a known warning rather than treating it as an unexpected
deployment failure.

Measured on 2026-09-11 with cached base layers: scene distribution took 7 s, a
successful aircraft ROS build took 24.1 s, the ground ROS build took 49.1 s,
and the complete parallel `scenes ; sync` run took 121 s (114 s for `sync`).
Network image resolution and an uncached build can take longer; these are
observed timings, not a deadline.

`remote/.bash_aliases` now contains only the container-era aircraft helpers,
including `deploy-doctor` for the read-only deployment health check.
Copy it to `~/.bash_aliases` on the Orin:

```
pxs status      # invoke any PX4Sim command from any directory
deploy-doctor   # check the deployed aircraft without changing state
```

The container is the path this aircraft flies. The former `onboard-native`,
`uspi<N>`, camera-forwarding, calibration, and recording aliases were removed
from the active file; they belonged to the pre-container deployment.

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

# Pilot camera tuning

The IMX477 pilot camera's white balance, saturation and exposure come from
`PILOT_CAMERA` in `remote/rtsp_config.py`. See
[`remote/CAMERA_TUNING.md`](remote/CAMERA_TUNING.md) for how to try settings
without editing the repo, measure them with `local/tune_pilot_camera.sh`, and
roll the winner out with `sync`.

# Thermal camera setup

The Boson's palette (black hot, which our detectors do much better on), AGC
tuning, gain mode and noise filters are settings in the camera's flash, not in
the repo. Which camera the detector reads is a fleet selector on the ground.

## Day and night

Night detects on the thermal camera. Day detects on the gimbal RGB camera (v3)
or the pilot camera (v2). Choose on the ground laptop with `n` in
`./px4sim ui`, or `./px4sim camera day|night` in `~/px4-sim-stack`. The choice
is `ONBOARD_CAMERA` in the ground `.env`, and `sync` copies it to every drone
the way it copies the scene, restarting a stack whose value changed (not with
`--no-build`). Unset counts as day.

## Each drone, once per camera

1. Deploy, or `sync`. `deploy.sh` installs flirpy and adds the user to
   `dialout`, which owns the Boson's serial port. On a drone deployed before
   that, run these once, then log in again:

   ```
   python3 -m pip install --user pyserial==3.5
   python3 -m pip install --user --no-deps flirpy==0.6.2
   sudo usermod -aG dialout "$USER"
   ```

   Keep `--no-deps`: flirpy's own dependencies pull in numpy 2, which the
   pinned torch cannot use.

2. Apply the camera settings, on the drone:

   ```
   cd ~/chimera-deploy/remote
   ./boson_setup.py            # report, and what --apply would change
   ./boson_setup.py --apply    # apply and save to camera flash; the stream changes at once
   ```

3. Chimera v3 (UAS 1–2) only: `./boson_averager.py --on`, then power cycle the
   camera.

4. Check it. `./remote/deploy_doctor.sh` warns when the Boson is off these
   settings, or a v3's averager is off. On the laptop, `thermall<N>` from lcam
   (`rtsp://127.0.0.1:8554/thermall3` for UAS 3) should show people dark on a
   lighter background.

After a camera swap, repeat steps 2 to 4.

## What --apply sets, and how to undo it

`--apply` sets black hot and moves two AGC settings as FLIR's datasheet
suggests for black hot and people: ACE 0.97 -> 1.03 and linear percent 20 -> 30.
Everything else stays at the camera's factory tuning.

```
./boson_setup.py --factory  # FLIR's factory settings (white hot), saved; keeps the averager
./boson_setup.py --apply    # back to the Chimera settings
```

Add `--no-save` to either to try it until the camera loses power. The docstring
in `remote/boson_setup.py` says what each setting does, what the AGC changes
measured, and why radiometry needs pipeline work instead.
