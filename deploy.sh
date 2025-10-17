# git repo
git clone --recurse-submodules git@github.com:UMD-UROC/chimera-deploy.git
cd chimera-deploy


# wifi drivers
sudo apt update
sudo apt install linux-headers-generic build-essential git
cd submodules/rtw88
make
sudo make install
sudo make install_fw
cd ../..
# reboot and then use nmtui to configure wifi

# echotherm daemon (thermal cam setup)
cd submodules/EchoTherm-Daemon
sudo ./install.sh
echothermd --daemon
cd ../..

# imx477 setup
sudo vi /boot/extlinux/extlinux.conf
# add these
      FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
      OVERLAYS /boot/tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo
# host
git clone git@github.com:EchoMAV/Camera_Modules.git
sudo cp submodules/Camera_Modules/overlays/tegra234-p3767-camera-p3768-imx477-custom-echopilot-ai-overlay.dtbo /boot
sudo /opt/nvidia/jetson-io/config-by-hardware.py # 24 pin csi, echomav imx477

