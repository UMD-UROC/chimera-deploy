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

sudo apt autoremove

echo "Done, don't forget to set network settings and send host ssh key. Power cycle to complete"
