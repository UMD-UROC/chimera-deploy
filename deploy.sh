# wifi drivers
sudo apt update && sudo apt upgrade -y
sudo apt install -y linux-headers-generic build-essential git
cd submodules/rtw88
make
sudo make install
sudo make install_fw
cd ../..

#cd submodules/EchoTherm-Daemon
#sudo ./install.sh
#cd ../..
