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
      ipv4.method manual ipv4.addresses 10.200.142.5${UAS_NUM}/24 \
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

# install yolo stuff for cuda
pip3 uninstall -y torch torchvision torchaudio
pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/02f/de421eabbf626/torch-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=02fde421eabbf62633092de30405ea4d917323c55bea22bfd10dfeb1f1023506 # torch 2.9.1 cuda
pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d12/bede7113e6b00/torchaudio-2.9.1-cp310-cp310-linux_aarch64.whl#sha256=d12bede7113e6b00f7c5ed53a28f7fa44a624780c8097a6a2352f32548d77ffb # torch audio 2.9.1 cuda
pip3 install https://pypi.jetson-ai-lab.io/jp6/cu126/+f/d5b/caaf709f11750/torchvision-0.24.1-cp310-cp310-linux_aarch64.whl#sha256=d5bcaaf709f11750b5bb0f6ec30f37605da2f3d5cb3cd2b0fe5fac2850e08642 # torch vision 2.9.1 cuda

pip3 uninstall -y ultralytics
pip3 install ultralytics

cd
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/arm64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get -y install cusparselt-cuda-12 cudss libcudnn9-cuda-12 # may only need cudss

# mavros
sudo apt install ros-humble-mavros
wget https://raw.githubusercontent.com/mavlink/mavros/ros2/mavros/scripts/install_geographiclib_datasets.sh
chmod +x install_geographiclib_datasets.sh
sudo ./install_geographiclib_datasets.sh

echo "Done, don't forget to set network settings if haven't already. Power cycle to and confirm ssh connects from host to complete!"

