# set uas number
read -p "Enter UAS number: " UAS_NUM

# confirm uas number
read -p "Is $UAS_NUM correct? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Exiting."
    exit 1
fi

# download source
mkdir -p ~/Orin
tar xpf local/Jetson_Linux_r36.4.4_aarch64.tbz2 -C ~/Orin

sudo tar xpf local/Tegra_Linux_Sample-Root-Filesystem_r36.4.4_aarch64.tbz2 -C ~/Orin/Linux_for_Tegra/rootfs/
cd ~/Orin/Linux_for_Tegra
sudo ./apply_binaries.sh
sudo tools/l4t_create_default_user.sh -u user -p Talon240 -n d$UAS_NUM -a --accept-license
cd ../../..

cd submodules/echopilot_ai_bsp
sudo ./install_l4t_orin.sh ~/Orin/Linux_for_Tegra/
cd ../..


echo <<EOF
NEED TO DO THE FOLLOWING MANUALLY

# plug in micro usb and hold recovery button
cd ~/Orin/Linux_for_Tegra/
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
ssh-copy-id -i ~/.ssh/id_rsa.pub user@192.168.1.220


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

## set up git
# orin
ssh-keygen -t rsa -b 4096
cat /home/user/.ssh/id_rsa.pub # add this to your github account ssh keys
git clone git@github.com:UMD-UROC/chimera-deploy.git
cd chimera-deploy

EOF

