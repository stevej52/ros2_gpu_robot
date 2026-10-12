#!/bin/bash
# test_cam.sh NAME LIVE_ONOFF(0|1) [extra -p args...]: realsense2_camera (rs259) alone on domain 55;
# LIVE_ONOFF=1 sets emitter_on_off true 6 s after start. Reports errors, the IR rate, the param.
R=/workspaces/isaac_ros-dev/rs259
source /opt/ros/jazzy/setup.bash; source $R/ws/install/setup.bash; export LD_LIBRARY_PATH=$R/prefix/lib:$LD_LIBRARY_PATH
export ROS_DOMAIN_ID=55 FASTRTPS_DEFAULT_PROFILES_FILE=/workspaces/isaac_ros-dev/fastdds_udp_only.xml
name=$1; live=$2; shift 2
$R/ws/install/realsense2_camera/lib/realsense2_camera/realsense2_camera_node --ros-args -r __ns:=/camera -r __node:=camera \
  -p enable_infra1:=true -p enable_infra2:=true -p enable_depth:=true -p enable_color:=false \
  -p depth_module.infra_profile:=640,360,90 -p depth_module.depth_profile:=640,360,90 "$@" > /tmp/cam_$name.log 2>&1 &
P=$!; sleep 6
[ "$live" = 1 ] && timeout 10 ros2 param set /camera/camera depth_module.emitter_on_off true >> /tmp/cam_$name.log 2>&1
sleep 2
probe=$(timeout 15 python3 $R/speckle_probe.py 2>&1 | tail -1)
hz=$(timeout 5 ros2 topic hz /camera/camera/infra1/image_rect_raw 2>/dev/null | grep -m1 "average rate")
v=$(timeout 8 ros2 param get /camera/camera depth_module.emitter_on_off 2>&1)
kill -INT $P; for i in 1 2 3 4 5 6; do kill -0 $P 2>/dev/null || break; sleep 1; done; kill -9 $P 2>/dev/null; wait $P 2>/dev/null
echo "== $name: ${hz:-NO FRAMES} | on_off: $v"; echo "   probe: $probe"; grep -E "ERROR|Failed to set|Error starting|Set parameter|hwmon" /tmp/cam_$name.log | cut -c1-200 | head -3
