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
# reboot and then use nmtui to configure wifi before it will work

# echotherm daemon (thermal cam setup)
cd submodules/EchoTherm-Daemon
sudo ./install.sh
echothermd --daemon
cd ../..

# imx477 setup
sudo cp remote/board.py /opt/nvidia/jetson-io/Jetson/board.py
sudo /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Camera IMX477 Custom Echopilot Overlay"
# need to reboot before it will work

