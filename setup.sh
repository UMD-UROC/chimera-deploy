# get script dir
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# set uas number
read -p "Enter UAS number: " UAS_NUM

# confirm uas number
read -p "Is $UAS_NUM correct? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Exiting."
    exit 1
fi

# download and install source
DOWNLOAD_PATH=$HOME/Downloads
wget -P $DOWNLOAD_PATH -N https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/Jetson_Linux_r36.4.4_aarch64.tbz2
wget -P $DOWNLOAD_PATH -N https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2
wget -P $DOWNLOAD_PATH -N https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/sources/public_sources.tbz2

# linux
ORIN=$HOME/Orin
if [ -d "$ORIN" ]; then
  echo "$ORIN folder exists, skip extracting 'Jetson_Linux_r36.4.4_aarch64.tbz2'"
else
  echo "extracting 'Jetson_Linux_r36.4.4_aarch64.tbz2'..."
  mkdir -p $ORIN
  sudo tar xpf $DOWNLOAD_PATH/Jetson_Linux_r36.4.4_aarch64.tbz2 -C $ORIN
fi

# rootfs
ROOTFS="$HOME/Orin/Linux_for_Tegra/rootfs"
if [ "$(find "$ROOTFS" -mindepth 1 -maxdepth 1 | wc -l)" -le 1 ]; then
  echo "extracting 'Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2'..."
  sudo tar xpf $DOWNLOAD_PATH/Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2 -C $ROOTFS
  echo "applying binaries..."
  cd $ORIN/Linux_for_Tegra
  sudo ./apply_binaries.sh
else
  echo "$ROOTFS has files, skip extracting 'Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2' and applying binaries"
fi

# delete all non-system users (UID >= 1000)
sudo chroot "$ROOTFS" bash -c 'userdel -r user 2>/dev/null || true'
# create desired user
cd $ORIN/Linux_for_Tegra
sudo tools/l4t_create_default_user.sh -u user -p Talon240 -n d$UAS_NUM -a --accept-license

echo "installing 'echopilot_ai_bsp'..."
cd $SCRIPT_DIR/submodules/echopilot_ai_bsp
sudo ./install_l4t_orin.sh $HOME/Orin/Linux_for_Tegra/
cd $SCRIPT_DIR

cat << EOF
===============================================================================
================== NEED TO DO THE FOLLOWING TO FLASH MANUALLY =================
===============================================================================

# plug in micro usb and hold recovery button
cd $HOME/Orin/Linux_for_Tegra/
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_external.xml -p "-c bootloader/generic/cfg/flash_t234_qspi.xml --no-systemimg" --network usb0 echopilot-ai external

## power cycle and plug in ethernet to router, remove micro usb and plug in usb c to orin

# host
picocom /dev/ttyUSB? -b 115200

# orin
ifconfig # to get ip
sudo ssh-keygen -A
sudo systemctl restart ssh

# host
ssh-keygen -t rsa -b 4096 # unless already exists
ssh-copy-id -i $HOME/.ssh/id_rsa.pub user@192.168.1.220

## set up git
# orin
ssh-keygen -t rsa -b 4096
cat /home/user/.ssh/id_rsa.pub # add this to your github account ssh keys
git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
cd chimera-deploy
git submodule update --init --recursive # to update submodules

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

EOF

