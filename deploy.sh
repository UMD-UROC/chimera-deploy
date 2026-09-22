#!/usr/bin/env bash
set -euo pipefail

DEPLOY_START=$SECONDS
STEP_START=$SECONDS
STEP_NUMBER=0

section() {
    STEP_NUMBER=$((STEP_NUMBER + 1))
    STEP_START=$SECONDS
    echo
    echo "================================================================"
    echo "STEP ${STEP_NUMBER}: $1"
    echo "Estimated time: $2"
    echo "================================================================"
}

step_done() {
    local elapsed=$((SECONDS - STEP_START))
    local total=$((SECONDS - DEPLOY_START))
    echo "Completed in ${elapsed}s (total elapsed: ${total}s)."
}

deploy_done() {
    echo
    echo "================================================================"
    echo "DEPLOYMENT SECTIONS COMPLETE"
    echo "Total elapsed time: $((SECONDS - DEPLOY_START))s"
    echo "================================================================"
}

# -----------------------------------------------------------------------------
# 1. Deployment identity and persistent environment
# Estimate: 30 seconds (measured after the first hardware run)
# -----------------------------------------------------------------------------
section "deployment identity and environment" "~30 seconds (provisional)"
# set uas number
read -r -p "Enter UAS number: " UAS_NUM

# confirm uas number
read -r -p "Is $UAS_NUM correct? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Exiting."
    exit 1
fi
case "$UAS_NUM" in
    1|2|3|4) ;;
    *) echo "UAS number must be 1-4 (the declared Chimera fleet)." >&2; exit 1 ;;
esac
read -r -p "Is this Chimera v2 or v3? [v3]: " UAS_MODEL
UAS_MODEL=${UAS_MODEL:-v3}
case "$UAS_MODEL" in
    v2|v3) ;;
    *) echo "Chimera model must be v2 or v3." >&2; exit 1 ;;
esac
echo "Selected Chimera model: $UAS_MODEL"

# set as environment variables, once. PX4Sim reads the aircraft settings from
# the generated stack environment.
export UAS_NUM
grep -qxF "UAS_NUM=${UAS_NUM}" /etc/environment \
  || echo "UAS_NUM=${UAS_NUM}" | sudo tee -a /etc/environment
export ROS_DOMAIN_ID=$((60 + UAS_NUM))
grep -qxF "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}" /etc/environment \
  || echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}" | sudo tee -a /etc/environment
grep -qxF "CHIMERA_MODEL=${UAS_MODEL}" /etc/environment \
  || echo "CHIMERA_MODEL=${UAS_MODEL}" | sudo tee -a /etc/environment
step_done

# -----------------------------------------------------------------------------
# 2. Airframe-specific network setup
# Estimate: 30-60 seconds for v3 wired setup, 2-10 minutes for v2 driver setup
# -----------------------------------------------------------------------------
section "${UAS_MODEL} network setup" "model-dependent; provisional"
if ! command -v nmcli >/dev/null || ! command -v ip >/dev/null; then
    echo "nmcli and ip are required for network setup." >&2
    exit 1
fi
if [[ "$UAS_MODEL" == v3 ]]; then
    # Chimera v3 has no Wi-Fi module. Its test/ground link is the wired
    # RoboScout interface. Configure it without changing Wi-Fi, bringing the
    # interface down, or adding a default route.
    ROBO_IF=${ROBO_IF:-$(nmcli -t -f DEVICE,TYPE,STATE device status \
        | awk -F: '$2 == "ethernet" && $3 == "connected" { print $1; exit }')}
    ROBO_CON=${ROBO_CON:-RoboScout-silvus}
    ROBO_ADDR=${ROBO_ADDR:-10.200.142.6${UAS_NUM}/24}
    [ -n "$ROBO_IF" ] || {
        echo "No connected Ethernet interface found; refusing to change networking." >&2
        exit 1
    }
    ip link show "$ROBO_IF" >/dev/null 2>&1 || {
        echo "$ROBO_IF is not present; refusing to change networking." >&2
        exit 1
    }
    ACTIVE_ROBO_CON=$(nmcli -t -f NAME,DEVICE connection show --active \
        | awk -F: -v dev="$ROBO_IF" '$2 == dev { print $1; exit }')
    if [ -n "$ACTIVE_ROBO_CON" ]; then
        ROBO_CON="$ACTIVE_ROBO_CON"
        if ! nmcli -g ipv4.addresses connection show "$ROBO_CON" \
            | tr ',' '\n' | grep -qx "$ROBO_ADDR"; then
            sudo nmcli connection modify "$ROBO_CON" +ipv4.addresses "$ROBO_ADDR"
        fi
    else
        if nmcli -t -f NAME connection show | grep -Fxq "$ROBO_CON"; then
            sudo nmcli connection modify "$ROBO_CON" \
                connection.interface-name "$ROBO_IF" \
                ipv4.method manual ipv4.addresses "$ROBO_ADDR" \
                ipv4.gateway "" ipv4.never-default yes connection.autoconnect yes
        else
            sudo nmcli connection add type ethernet ifname "$ROBO_IF" \
                con-name "$ROBO_CON" ipv4.method manual \
                ipv4.addresses "$ROBO_ADDR" ipv4.gateway "" \
                ipv4.never-default yes connection.autoconnect yes
        fi
    fi
    if ! ip -4 addr show dev "$ROBO_IF" | grep -qE "inet ${ROBO_ADDR%/*}/"; then
        sudo ip addr add "$ROBO_ADDR" dev "$ROBO_IF"
    fi
    echo "RoboScout is configured as $ROBO_IF with $ROBO_ADDR (no default route)."
    echo "After the ground station is connected, run local/share-on.sh there, then:"
    echo "  sudo ip route replace default via 10.200.142.60 dev $ROBO_IF"
else
    # Chimera v2 uses the rtw88 Wi-Fi module. Do not run this branch on v3.
    sudo apt update
    sudo apt install --no-upgrade -y linux-headers-generic build-essential git
    cd submodules/rtw88
    make
    sudo make install
    sudo make install_fw
    cd ../..
    echo "v2 Wi-Fi driver installed; no reboot or Wi-Fi reconfiguration was run."
fi
step_done

# -----------------------------------------------------------------------------
# 3. Thermal sensor daemon
# Estimate: 1-3 minutes (measured after the first hardware run)
# -----------------------------------------------------------------------------
section "thermal sensor daemon" "~1-3 minutes (provisional)"
# git repo
if [[ "$PWD" != *chimera-deploy* ]]; then
    git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
    cd chimera-deploy || exit 1
fi

# echotherm daemon (thermal cam setup)
cd submodules/EchoTherm-Daemon
if command -v echothermd >/dev/null && command -v echotherm >/dev/null; then
    echo "EchoTherm is already installed; skipping package/build step."
else
    sudo ./install.sh
fi
if pgrep -x echothermd >/dev/null 2>&1; then
    echo "echothermd is already running."
else
    nohup echothermd --daemon >/tmp/echothermd.log 2>&1 </dev/null &
fi
cd ../..
step_done

# -----------------------------------------------------------------------------
# 4. CSI camera overlay configuration
# Estimate: 30-60 seconds; reboot intentionally not performed here
# -----------------------------------------------------------------------------
section "CSI camera overlay configuration" "~30-60 seconds (no reboot)"
# imx477 setup
# copy overlay to boot
sudo cp submodules/Camera_Modules/overlays/tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo /boot
# update boot configuration
CONF=/boot/extlinux/extlinux.conf
APPEND_LINE=$(grep -m1 'APPEND ' "$CONF")
# Remove any existing "LABEL Custom" section (including its header)
sudo sed -i '/^LABEL Custom$/,/^LABEL \|^$/d' "$CONF"
# Append the new Custom entry
sudo tee -a "$CONF" >/dev/null <<EOF
LABEL Custom
      MENU LABEL Custom Header Config: <CSI Camera IMX477 Custom Echopilot Overlay>
      LINUX /boot/Image
      INITRD /boot/initrd
$APPEND_LINE
      FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
      OVERLAYS /boot/tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo
EOF
# Set default boot option to Custom entry with imx477 overlay
sudo sed -i 's/^DEFAULT .*/DEFAULT Custom/' /boot/extlinux/extlinux.conf
echo "Camera overlay configured; activation requires a later planned reboot."
step_done

# -----------------------------------------------------------------------------
# 5. Native camera/RTSP service
# Estimate: 1-2 minutes (measured after the first hardware run)
# -----------------------------------------------------------------------------
section "native camera and RTSP service" "~1-2 minutes (provisional)"
# rtsp server
sudo apt install --no-upgrade -y gir1.2-gst-rtsp-server-1.0 python3-gi

# rtsp server as service
sudo cp remote/rcam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rcam.service
sudo systemctl stop rcam.service 2>/dev/null || true
if timeout 10 gst-launch-1.0 -q nvarguscamerasrc sensor-id=0 num-buffers=1 ! fakesink >/dev/null 2>&1; then
    sudo systemctl start rcam.service
    echo "CSI camera is responding; rcam.service started."
else
    echo "CSI camera is not responding in this boot; rcam.service enabled but not started."
    echo "After the planned reboot, rerun this script to verify the camera and start rcam.service."
fi
step_done

# -----------------------------------------------------------------------------
# 6. Native MAVLink routing
# Estimate: 10-20 seconds when the router is already installed
# -----------------------------------------------------------------------------
section "native MAVLink routing" "~10-20 seconds (router already installed)"
if ! command -v mavlink-routerd >/dev/null 2>&1; then
    echo "mavlink-routerd is not installed." >&2
    read -r -p "Run the legacy EchoMAV installer (Cockpit, temperature.service, and extra tools too)? [y/N]: " install_legacy
    if [[ "$install_legacy" =~ ^[Yy]$ ]]; then
        (cd submodules/echopilot_deploy && ./deploy.sh no-static)
    else
        echo "Router installation declined. See legacy/README.md." >&2
        exit 1
    fi
fi
if ! systemctl cat mavlink-router.service >/dev/null 2>&1; then
    sudo install -m 644 submodules/echopilot_deploy/mavlink-router.service \
        /lib/systemd/system/mavlink-router.service
    sudo systemctl daemon-reload
fi

# Write only the PX4Sim/native-router configuration.
GCS_PORT=$((14550 + UAS_NUM)) envsubst < ./remote/main.conf.template | sudo tee /etc/mavlink-router/main.conf > /dev/null

sudo systemctl enable mavlink-router.service
sudo systemctl restart mavlink-router.service
step_done

# -----------------------------------------------------------------------------
# 7. Clock synchronization
# Estimate: 30-90 seconds, depending on ground-station reachability
# -----------------------------------------------------------------------------
section "clock synchronization" "~30-90 seconds (provisional)"
# chrony
# TODO: consider changing makestep 1 3 > 1 -1 to always update from laptop
sudo apt install --no-upgrade chrony -y
grep -qxF "server 10.200.142.60 iburst" /etc/chrony/chrony.conf || echo "server 10.200.142.60 iburst" | sudo tee -a /etc/chrony/chrony.conf # add 10.200.142.60 as chrony server
sudo systemctl restart chrony
date # verify
step_done

# -----------------------------------------------------------------------------
# 8. Onboard px4-sim-stack deployment
# Estimate: 1-10 minutes; clone/model resolution/build availability vary
# -----------------------------------------------------------------------------
section "onboard px4-sim-stack deployment" "~1-10 minutes (provisional)"
# the onboard container: docker access, px4-sim-stack, its .env, and models.
# The flight repos must be on the machine first. ./setup_git_server.sh remote
# clones them from the laptop git daemon.
./remote/deploy_onboard.sh || exit 1
step_done

# quit before wip stuff
deploy_done
exit 0

### follow docs for ros install

mkdir -p ~/ros2_ws/src

# ros message packages
sudo apt install --no-upgrade -y \
  ros-humble-builtin-interfaces \
  ros-humble-domain-bridge \
  ros-humble-geographic-msgs \
  ros-humble-geometry-msgs \
  ros-humble-mavros-msgs \
  ros-humble-nav-msgs \
  ros-humble-rcl-interfaces \
  ros-humble-sensor-msgs \
  ros-humble-std-msgs \
  ros-humble-vision-msgs \
  ros-humble-visualization-msgs
  

cdr
sudo rosdep init
rosdep install --from-paths src --ignore-src -r -y
  
  
  # confirmed
sudo apt install --no-upgrade -y \
  ros-humble-vision-msgs \
  ros-humble-domain-bridge \
  ros-humble-cv-bridge \
  ros-humble-rosbag2-storage-mcap \
  ros-humble-foxglove-msgs
    
pip install pymap3d folium

# torch
pip install --no-deps ultralytics
pip uninstall -y torch torchvision torchaudio ultralytics && \
pip install --no-cache-dir https://pypi.jetson-ai-lab.io/jp6/cu126/+f/02f/de421eabbf626/torch-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=02fde421eabbf62633092de30405ea4d917323c55bea22bfd10dfeb1f1023506 # torch 2.9.1 cuda
pip install --no-cache-dir https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d12/bede7113e6b00/torchaudio-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=d12bede7113e6b00f7c5ed53a28f7fa44a624780c8097a6a2352f32548d77ffb # torch audio 2.9.1 cuda
pip install --no-cache-dir https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d5b/caaf709f11750/torchvision-0.24.1-cp310-cp310-linux_aarch64.whl#sha256=d5bcaaf709f11750b5bb0f6ec30f37605da2f3d5cb3cd2b0fe5fac2850e08642 # torch vision 2.9.1 cuda
pip install --user --force-reinstall 'numpy<2'
pip install --no-deps ultralytics
pip install onnx
pip install ftfy regex tqdm
pip install git+https://github.com/openai/CLIP.git
pip install onnxscript

# cuda ss
cd ~
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/arm64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install --no-upgrade -y cudss

# pyds
# may not need these two lines
sudo /opt/nvidia/deepstream/deepstream/install.sh
sudo ldconfig

cd /tmp
wget -O pyds-1.2.0-cp310-cp310-linux_aarch64.whl \
  https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/releases/download/v1.2.0/pyds-1.2.0-cp310-cp310-linux_aarch64.whl
python3 -m pip install --user --force-reinstall \
  ./pyds-1.2.0-cp310-cp310-linux_aarch64.whl

# mavros (after ros install)
sudo apt install --no-upgrade -y ros-humble-mavros ros-humble-mavros-extras
wget https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh
chmod +x install_geographiclib_datasets.sh
sudo ./install_geographiclib_datasets.sh

# mavros patch for PX4 v1.18: the stock package asks for autopilot capabilities
# with a command v1.18 removed, and then falls back to no capabilities at all.
# See remote/mavros_patch/README.md.
git submodule update --init submodules/mavros submodules/angles
./remote/mavros_patch/apply.sh

# TODO
##ros domain id
#echo 'export ROS_DOMAIN_ID=64' >> ~/.bashrc
#source ~/.bashrc

# get docker containers for ml
# install the container tools
#git clone https://github.com/dusty-nv/jetson-containers
#bash jetson-containers/install.sh

# install yolo stuff for cuda
#pip3 uninstall -y torch torchvision torchaudio
#pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/02f/de421eabbf626/torch-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=02fde421eabbf62633092de30405ea4d917323c55bea22bfd10dfeb1f1023506 # torch 2.9.1 cuda
#pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d12/bede7113e6b00/torchaudio-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=d12bede7113e6b00f7c5ed53a28f7fa44a624780c8097a6a2352f32548d77ffb # torch audio 2.9.1 cuda
#pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d5b/caaf709f11750/torchvision-0.24.1-cp310-cp310-linux_aarch64.whl#sha256=d5bcaaf709f11750b5bb0f6ec30f37605da2f3d5cb3cd2b0fe5fac2850e08642 # torch vision 2.9.1 cuda

#pip3 uninstall -y ultralytics
#pip3 install ultralytics

#cd
#wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/arm64/cuda-keyring_1.1-1_all.deb
#sudo dpkg -i cuda-keyring_1.1-1_all.deb
#sudo apt-get update
#sudo apt-get -y install cusparselt-cuda-12 cudss libcudnn9-cuda-12 # may only need cudss

sudo apt autoremove -y

echo "Done, don't forget to set network settings if haven't already. Power cycle to and confirm ssh connects from host to complete!"

# chrony
sudo apt install --no-upgrade chrony -y
grep -qxF "server 10.200.142.60 iburst" /etc/chrony/chrony.conf || echo "server 10.200.142.60 iburst" | sudo tee -a /etc/chrony/chrony.conf # add 10.200.142.60 as chrony server
sudo systemctl restart chrony
date # verify
