#!/bin/bash
# cuvslam_run.sh NAME INFRA_PROFILE EMITTER JITTER_MS [DUR]
# Restart cuVSLAM in the isaac_vo container with the given RealSense IR profile, measure DUR s, append to summary.
set +u
source /opt/ros/jazzy/setup.bash; source ~/ros2_ws/install/setup.bash; export ROS_DOMAIN_ID=7
NAME=$1; PROFILE=$2; EMITTER=$3; JITTER=$4; DUR=${5:-60}
OUT=~/vo-sweep-2026-09-23; mkdir -p $OUT
PROF=/workspaces/isaac_ros-dev/fastdds_udp_only.xml
docker exec isaac_vo pkill -INT -f "ros2 launch" 2>/dev/null
for i in $(seq 1 15); do docker exec isaac_vo pgrep -f "component_container|realsense2_camera_node" >/dev/null || break; sleep 1; done
docker exec isaac_vo pgrep -f "component_container|realsense2_camera_node" >/dev/null && { docker exec isaac_vo pkill -TERM -f "component_container|realsense2_camera_node"; sleep 3; }
sleep 2
nohup docker exec -u root -e FASTRTPS_DEFAULT_PROFILES_FILE=$PROF isaac_vo bash -c "source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=7; exec ros2 launch /workspaces/isaac_ros-dev/cuvslam_d435_stereo.launch.py infra_profile:=$PROFILE emitter:=$EMITTER image_jitter_threshold_ms:=$JITTER" > $OUT/$NAME.node.log 2>&1 &
sleep 30
echo "=== $NAME profile=$PROFILE emitter=$EMITTER jitter=$JITTER ($(date +%H:%M:%S))"
printf "   infra1 hz: "; timeout 8 ros2 topic hz /camera/infra1/image_rect_raw --window 30 2>/dev/null | grep -m1 -oE "[0-9.]+$" || echo none
top -b -d 5 -n $((DUR/5)) > $OUT/$NAME.top.log 2>&1 &
TP=$!
( sleep 10; timeout 8 tegrastats --interval 2000 ) > $OUT/$NAME.tegra.log 2>&1 &
TG=$!
python3 ~/vo_probe.py $DUR 2>/dev/null | tail -1 > $OUT/$NAME.probe.json
wait $TP $TG
cpu () { grep -E "$1" $OUT/$NAME.top.log | awk '{s+=$9;n++} END{if(n) printf "%.1f", s/n; else print "na"}'; }
VS=compone
LINE="$NAME cpu_cuvslam=$(cpu "${VS:-component_container}") cpu_realsense=$(cpu realsen) cpu_ekf=$(cpu ekf_node) gpu=$(grep -oE 'GR3D_FREQ [0-9]+%' $OUT/$NAME.tegra.log | tail -n1) ram=$(grep -oE 'RAM [0-9/]+MB' $OUT/$NAME.tegra.log | tail -n1) jitter_warn=$(grep -c 'above threshold' $OUT/$NAME.node.log) $(tr -d '\n' < $OUT/$NAME.probe.json)"
echo "$LINE" | tee -a $OUT/summary.txt
echo "   vo_state: $(docker exec -e FASTRTPS_DEFAULT_PROFILES_FILE=$PROF isaac_vo bash -c 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=7; timeout 5 ros2 topic echo --once /visual_slam/status 2>/dev/null | grep -oE "vo_state: [0-9]+"')"
