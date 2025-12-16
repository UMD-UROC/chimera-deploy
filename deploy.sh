# set uas number
read -p "Enter UAS number: " UAS_NUM

# confirm uas number
read -p "Is $UAS_NUM correct? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Exiting."
    exit 1
fi

# set as environment variable
export UAS_NUM
echo "UAS_NUM=${UAS_NUM}" | sudo tee -a /etc/environment
source /etc/environment

# git repo
if [[ "$PWD" != *chimera-deploy* ]]; then
    git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
    cd chimera-deploy || exit 1
fi

# wifi drivers
sudo apt update
sudo apt install -y linux-headers-generic build-essential git
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
# need to reboot before it will work

# rtsp server
sudo apt install -y gir1.2-gst-rtsp-server-1.0 python3-gi
cp remote/multi_rtsp_server.py ~

# rtsp server as service
sudo cp remote/rcam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start rcam.service
sudo systemctl enable rcam.service

# echomav deploy
cd submodules/echopilot_deploy/
./deploy.sh no-static
cd ../..

# mavlink router
envsubst < ./remote/main.conf.template | sudo tee /etc/mavlink-router/main.conf > /dev/null

sudo systemctl enable mavlink-router.service
sudo systemctl restart mavlink-router.service

# use nmcli to configure the network appropriately
if ! nmcli -t -f NAME connection show | grep -Fxq "RoboScout-silvus"; then
    sudo nmcli connection add type ethernet \
      ifname eno1 con-name RoboScout-silvus \
      ipv4.method manual ipv4.addresses 10.200.91.5${UAS_NUM}/24 \
      connection.autoconnect yes
else
    echo "Existing \"RoboScout-silvus\" connection detected — skipping creation."
fi

  
# use nmtui to add any other connections and modify to preference

# ssh
sudo ssh-keygen -A
sudo systemctl restart ssh

sudo apt autoremove -y

# get docker containers for ml
# install the container tools
git clone https://github.com/dusty-nv/jetson-containers
bash jetson-containers/install.sh

# automatically pull & run any container
#jetson-containers run $(autotag l4t-pytorch)

# hold the important packages, not sure if prevents breaking things if accidently apt upgrade
sudo apt-mark hold nvidia-l4t-bootloader nvidia-l4t-kernel nvidia-l4t-kernel-headers nvidia-l4t-jetson-io nvidia-l4t-kernel-oot-modules nvidia-l4t-display-kernel nvidia-l4t-kernel-oot-headers nvidia-l4t-kernel-dtbs

cd
cp chimera-deploy/local/.bash_aliases .
source .bash_aliases

echo "Done, don't forget to set network settings if haven't already. Power cycle to and confirm ssh connects from host to complete!"


### ROS ###

## ros install (https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)
# orin
sudo apt install -y software-properties-common
sudo add-apt-repository universe

# install apt source
sudo apt update && sudo apt install curl -y
export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F\" '{print $4}')
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"
sudo dpkg -i /tmp/ros2-apt-source.deb

sudo apt install -y ros-humble-ros-base ros-dev-tools
sudo apt install -y ros-$ROS_DISTRO-perception ros-$ROS_DISTRO-vision-msgs


cd
mkdir ros2_ws
cd ros2_ws
mkdir src
cd src
git clone git@github.com:UMD-CDCL/5g_drone.git
git clone git@github.com:UMD-CDCL/cdcl_umd_msgs.git
ccb

# should now be up to date on main branches








## install packages
#sudo apt update && sudo apt install -y python3-flake8-docstrings python3-pip python3-pytest-cov ros-dev-tools
#sudo apt install -y python3-flake8-blind-except python3-flake8-builtins python3-flake8-class-newline python3-flake8-comprehensions python3-flake8-deprecated python3-flake8-import-order python3-flake8-quotes python3-pytest-repeat python3-pytest-rerunfailures
#
## make workspace
#mkdir -p ~/ros2_ws/src
#cd ~/ros2_ws
#vcs import --input https://raw.githubusercontent.com/ros2/ros2/humble/ros2.repos src
#
## install ros deps
##sudo apt upgrade # got nvidia-l4t-* errors, I think to be expected with custom dtb and old jetpack
#
#sudo rosdep init
#rosdep update
#rosdep install --from-paths src --ignore-src -y --skip-keys "fastcdr rti-connext-dds-6.0.1 urdfdom_headers"
#
#cd ~/ros2_ws/
#colcon build --symlink-install # took me 2 hours on the orin




























