## driver setup
# basic updates
sudo apt update
sudo apt upgrade

# confirm nvidia driver and set to always use nvidia (for multi gpu machines)
nvidia-smi
sudo prime-select nvidia


## git install
# Use your GitHub email
ssh-keygen -t ed25519 -C "YOUR_EMAIL" # enter for defaults

# start ssh agent and add key
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub # print public key

# copy paste public key (output above) to github.com > settings > SSH and GPG keys > new SSH key

# add self
git config --global user.email "YOUR_EMAIL"
git config --global user.name "YOUR_USERNAME"

# test
ssh -T git@github.com


## install vcs
# install pip
sudo apt update
sudo apt install -y python3-pip

# install vcs
python3 -m pip install --user vcstool

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

## clone repos
# clean reinstall
cd ~/chimera-deploy
rm -rf ros2_ws/src/*
vcs import ros2_ws/src < docker/chimera.repos


## install mavlink router
# deps
sudo apt update
sudo apt install -y \
  git \
  meson \
  ninja-build \
  pkg-config \
  gcc \
  g++ \
  systemd \
  python3-pip

# install router
cd /tmp

rm -rf mavlink-router

git clone --recursive https://github.com/mavlink-router/mavlink-router.git
cd mavlink-router

meson setup build .
ninja -C build
sudo ninja -C build install
sudo ldconfig

# update settings and apply
sudo mkdir -p /etc/mavlink-router
sudo cp ~/chimera-deploy/local/main.conf /etc/mavlink-router/main.conf
sudo systemctl enable mavlink-router
sudo systemctl restart mavlink-router


## install qgc
# QGC runtime deps: serial access, video support, AppImage support, Qt/X11 deps
sudo apt update
sudo apt install -y \
  curl \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-libav \
  gstreamer1.0-gl \
  python3-gi \
  python3-gst-1.0 \
  libfuse2 \
  libxcb-xinerama0 \
  libxkbcommon-x11-0 \
  libxcb-cursor-dev

# Allow your user to access USB serial devices
sudo usermod -aG dialout "$(id -un)"

# Prevent ModemManager from grabbing Pixhawk / USB serial devices
sudo systemctl mask --now ModemManager.service

# Install QGC into your local app directory
mkdir -p "$HOME/Applications"

# Pick the correct official Linux AppImage for this CPU architecture
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)
    QGC_URL="https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl-x86_64.AppImage"
    QGC_FILE="$HOME/Applications/QGroundControl-x86_64.AppImage"
    ;;
  aarch64|arm64)
    QGC_URL="https://d176tv9ibo4jno.cloudfront.net/latest/QGroundControl-aarch64.AppImage"
    QGC_FILE="$HOME/Applications/QGroundControl-aarch64.AppImage"
    ;;
  *)
    echo "Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

curl -L "$QGC_URL" -o "$QGC_FILE"
chmod +x "$QGC_FILE"

# Make a stable symlink so launchers/scripts do not care about architecture
ln -sf "$QGC_FILE" "$HOME/Applications/QGroundControl.AppImage"

# Use QGC's own repo icon asset
mkdir -p "$HOME/.local/share/icons"

curl -L \
  "https://raw.githubusercontent.com/mavlink/qgroundcontrol/master/resources/QGCLogoFull.svg" \
  -o "$HOME/.local/share/icons/qgroundcontrol.svg"
  
# Add QGroundControl to your app launcher
mkdir -p "$HOME/.local/share/applications"

cat > "$HOME/.local/share/applications/qgroundcontrol.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=QGroundControl
Comment=Ground control station for MAVLink drones
Exec=$HOME/Applications/QGroundControl.AppImage
Icon=$HOME/.local/share/icons/qgroundcontrol.svg
Terminal=false
Categories=Utility;Robotics;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/qgroundcontrol.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true


## docker install
# Remove conflicting old packages
sudo apt remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc

# Add Docker official apt repo
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

# Install Docker Engine + Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
sudo systemctl enable --now docker

# Test
sudo docker run hello-world


## install cuda toolkit for docker
# Install NVIDIA Container Toolkit repo + package
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Register NVIDIA runtime with Docker
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker


## set up ros2
# clone repos
cd ros2_ws/src
git clone git@github.com:UMD-UROC/MAVInsight.git
git clone git@github.com:UMD-CDCL/5g_drone.git
git clone git@github.com:UMD-CDCL/cdcl_umd_msgs.git
git clone git@github.com:UMD-CDCL/manual_detector_gui.git
git clone git@github.com:UMD-CDCL/roboscout_uas_extras.git
git clone git@github.com:PX4/px4_msgs.git





















