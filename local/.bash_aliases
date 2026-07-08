#!/bin/bash

alias rs='source /opt/ros/humble/setup.bash'
alias ws='source install/setup.bash'
alias cdr='cd ~/ros2_ws; rs; ws'
alias cdv='cd ~/DTC/chimera-recording-visualization'
alias cdd='cd ~/chimera-deploy'
alias cd5='cdr; cd src/5g_drone'
alias cdc='cdr; cd src/cdcl_umd_msgs'
alias orin-usb='picocom /dev/ttyUSB? -b 115200 # login is j1 and pass oelinux123'
#alias fgb='cdr && cd - && ros2 launch foxglove_bridge foxglove_bridge_launch.xml # launch foxglove ros bridge'
alias fgb='cdr && cd - && ros2 launch umd_uas foxglove_bridge.launch.py # launch foxglove ros bridge'
alias view1='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 10.200.142.61'
alias view2='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 10.200.142.62'
alias view3='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 10.200.142.63'
alias view4='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 10.200.142.64'
alias view='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 10.200.142.60'
alias viewl='cd ~/chimera-deploy/local; ./view_rtsp_streams.sh -i 127.0.0.1'
alias record='cd ~/chimera-deploy/local; ./record_rtsp_streams.sh '
alias cam3='cd ~/chimera-deploy/local; ./start_camera_server.sh -u user -i 10.200.142.63'
alias cam4='cd ~/chimera-deploy/local; ./start_camera_server.sh -u user -i 10.200.142.64'
alias lcam='cd ~/chimera-deploy/local; ./local_start_camera_server.sh'
#alias lcam='cd ~/chimera-deploy/local; ./local_start_camera_server.sh -u ctitus -i 10.200.142.60'
alias uspi1='ccb && cdr && ros2 launch umd_uas uas1.launch.py && cd -'
alias uspi2='ccb && cdr && ros2 launch umd_uas uas2.launch.py && cd -'
alias uspi3='ccb && cdr && ros2 launch umd_uas uas3.launch.py && cd -'
alias uspi3-thermal='ccb && cdr && ros2 launch umd_uas uas3_thermal.launch.py && cd -'
alias uspi4='ccb && cdr && ros2 launch umd_uas uas4.launch.py && cd -'
alias uspi4-thermal='ccb && cdr && ros2 launch umd_uas uas4_thermal.launch.py && cd -'
alias uspi4-assess='ccb && cdr && ros2 launch umd_uas uas4_assess.launch.py && cd -'
alias uspi4-assess-no-gps='ccb && cdr && ros2 launch umd_uas uas4_assess_no_gps.launch.py && cd -'
alias uspi4-assess-no-gps-thermal='ccb && cdr && ros2 launch umd_uas uas4_assess_no_gps_thermal.launch.py && cd -'
alias netbridge='cdr && ros2 launch umd_uas netbridge.launch.py && cd -'
#alias bag='cdr; ros2 bag record -a -x "^(/uas1/image|/uas2/image|/uas3/image|/uas4/image)$"'
export BAG_REGEX=$(paste -sd '|' ~/ros2_ws/src/5g_drone/resource/rosbag_topics.txt)
alias bag='cdr && ros2 bag record -s mcap --storage-preset-profile zstd_fast -e "$BAG_REGEX"'
alias bgc='cd ~/Basecam/SimpleBGC_GUI_2_73_3; ./run.sh'
alias forward3='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/rgb3 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.41 port=5000 sync=false'
alias forward3-thermal='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/thermal3 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.41 port=5000 sync=false'
alias forward4='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/rgb4 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.41 port=5000 sync=false'
alias forward4-thermal='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/thermal4 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.41 port=5000 sync=false'
alias mosaic-images='cdr; python3 src/5g_drone/umd_uas/image_ground_mosaic_folium_targets_node.py --ros-args -p target_box_array_topic:=/uas4/target_locations -p camera_info_topic:=/uas4/camera/camera_info -p mosaic_topic:=/uas4/ground_mosaic -p mavros_home_position_topic:=/uas4/home_position/home -p use_home_as_ref:=true -p prefer_home_over_gps:=true -p lock_origin_after_home:=true -p ref_change_tol_m:=2.0 -p clear_on_ref_change:=true -p canvas_width_m:=200.0 -p canvas_height_m:=200.0 -p resolution_m_per_px:=0.06 -p canvas_origin_x:=-100.0 -p canvas_origin_y:=-100.0 -p blend_mode:=sharpest -p warp_interpolation:=auto -p export_folium:=true -p folium_html_path:=$HOME/mosaic_map.html -p overlay_png_path:=$HOME/mosaic_overlay.png -p crop_to_coverage:=true -p crop_pad_px:=10 -p fit_map_to_overlay:=true -p folium_tiles:=Esri.WorldImagery -p folium_max_native_zoom:=19 -p folium_max_zoom:=22 -p folium_no_wrap:=true -p overlay_alpha_mode:=binary -p overlay_alpha_threshold:=0.12 -p overlay_alpha_open_kernel:=2 -p overlay_opacity:=0.98 -p merge_distance_m:=4.0 -p show_target_pins:=true -p pin_style:=circle -p save_png_every_n_frames:=0'
alias mosaic-tileserver='cdr; python3 src/5g_drone/umd_uas/mosaic_tileserver.py --png "$HOME/mosaic_overlay.png" --bounds "$HOME/mosaic_overlay_bounds.json" --port 8888 --max-native-zoom 19 --allow-overzoom'
alias oal='open ~/.bash_aliases'
alias sal='source ~/.bash_aliases'
alias ssh1='ssh root@10.200.142.61'
alias ssh2='ssh root@10.200.142.62'
alias ssh3='ssh user@10.200.142.63'
alias ssh4='ssh user@10.200.142.64'
alias sshf11='ssh flyby@10.223.35.1'
alias ccb='cd ~/ros2_ws; colcon build; rs; ws; cd -'
alias camcal3='cdr; ros2 run camera_calibration cameracalibrator --size 5x7 --square 0.027 --ros-args -r image:=/uas3/image -p camera:=/drone'
alias camcal4='cdr; ros2 run camera_calibration cameracalibrator --size 5x7 --square 0.027 --ros-args -r image:=/uas4/image -p camera:=/drone'
alias mforward3='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/rgb3 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.102 sync=false' # port = XXXX
alias mforward3-thermal='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/thermal3 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.102 sync=false'
alias mforward4='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/rgb4 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.102 sync=false'
alias mforward4-thermal='gst-launch-1.0 rtspsrc location=rtsp://127.0.0.1:8554/thermal4 latency=0 ! rtph265depay ! h265parse ! rtph265pay config-interval=1 pt=96 ! udpsink host=10.200.142.102 sync=false'
alias f3a='mforward3 port=5001'
alias f3b='mforward3 port=5002'
alias f3c='mforward3 port=5003'
alias f3at='mforward3-thermal port=5001'
alias f3bt='mforward3-thermal port=5002'
alias f3ct='mforward3-thermal port=5003'
alias f4a='mforward4 port=5001'
alias f4b='mforward4 port=5002'
alias f4c='mforward4 port=5003'
alias f4at='mforward4-thermal port=5001'
alias f4bt='mforward4-thermal port=5002'
alias f4ct='mforward4-thermal port=5003'
alias ping3='ping 10.200.142.63'
alias ping4='ping 10.200.142.64'
alias bandwidth='sudo iftop -i enp132s0'
alias download-all='cd ~/Videos/uas && rsync -avzP user@10.200.142.63:/home/user/videos/*.ts ./d3 ; rsync -avzP user@10.200.142.64:/home/user/videos/*.ts ./d4'
alias sshc='ssh cdcl@192.168.79.165'
alias ra='cdr && ~/chimera-deploy/local/local_record_all.sh'
rdom () {
    if [ "$#" -eq 0 ]; then
        # "if ROS_DOMAIN_ID is unset, then ROS uses the default value of 0
        my_ros_id="${ROS_DOMAIN_ID:-0}"
        echo "ROS_DOMAIN_ID is $my_ros_id"
    elif [ "$#" -eq 1 ]; then
    	if ! [[ "$1" =~ ^[-]?[0-9]+$ ]]; then
            echo "Detected non-integer input. Please use an integer."
        elif [ "$1" -lt 0 ] || [ "$1" -gt 101 ]; then
            echo "Argument Error: out of range. Safe ROS_DOMAIN_ID range is (0-101)"
        else
            export ROS_DOMAIN_ID=$1
            echo "ROS_DOMAIN_ID has been set to $ROS_DOMAIN_ID"
        fi
    else
        echo "Argument Error: Too many arguments. rdom takes 0 or 1 arguments"
    fi
}
