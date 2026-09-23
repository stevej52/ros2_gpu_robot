#!/bin/bash
# Run rtabmap rgbd_odometry under several parameter sets, DUR seconds each, on the live D435.
# Records per config: probe JSON, top samples, tegrastats, node log; appends one line to summary.txt.
set +u
source /opt/ros/jazzy/setup.bash; source ~/ros2_ws/install/setup.bash; export ROS_DOMAIN_ID=7
OUT=~/vo-sweep-2026-09-23; mkdir -p "$OUT"
DUR=${DUR:-90}; WARM=${WARM:-15}
CONFIGS=(
  "A_f2m_baseline|"
  "B_f2f|Odom/Strategy=1 Vis/CorType=1 Odom/KeyFrameThr=0.6"
  "C_f2f_dec2|Odom/Strategy=1 Vis/CorType=1 Odom/KeyFrameThr=0.6 Odom/ImageDecimation=2"
  "D_f2f_feat500|Odom/Strategy=1 Vis/CorType=1 Odom/KeyFrameThr=0.6 Vis/MaxFeatures=500"
  "E_f2f_dec2_feat500|Odom/Strategy=1 Vis/CorType=1 Odom/KeyFrameThr=0.6 Odom/ImageDecimation=2 Vis/MaxFeatures=500"
  "F_f2m_dec2|Odom/ImageDecimation=2"
)
[ $# -gt 0 ] && CONFIGS=("$@")
REMAPS="-r rgb/image:=/camera/camera/color/image_raw -r rgb/camera_info:=/camera/camera/color/camera_info -r depth/image:=/camera/camera/aligned_depth_to_color/image_raw -r odom:=/vo"
for entry in "${CONFIGS[@]}"; do
  name=${entry%%|*}; params=${entry#*|}
  if pgrep -x rgbd_odometry >/dev/null; then echo "$name: rgbd_odometry already running - abort" | tee -a "$OUT/summary.txt"; break; fi
  yaml="$OUT/$name.yaml"
  { echo "/**:"; echo "  ros__parameters:"; echo "    frame_id: base_link"; echo "    odom_frame_id: odom"
    echo "    publish_tf: false"; echo "    approx_sync: true"; echo "    wait_imu_to_init: false"; echo "    subscribe_rgbd: false"
    for kv in $params; do k=${kv%%=*}; v=${kv#*=}; echo "    $k: \"$v\""; done; } > "$yaml"
  echo "=== $name  ($(date +%H:%M:%S))  params: [$params]"
  nohup ros2 run rtabmap_odom rgbd_odometry --ros-args --params-file "$yaml" $REMAPS > "$OUT/$name.node.log" 2>&1 &
  NPID=$!
  sleep "$WARM"
  top -b -d 5 -n $((DUR/5)) > "$OUT/$name.top.log" 2>&1 &
  TPID=$!
  ( sleep 20; timeout 8 tegrastats --interval 2000 ) > "$OUT/$name.tegra.log" 2>&1 &
  python3 ~/vo_probe.py "$DUR" > "$OUT/$name.probe.json" 2> "$OUT/$name.probe.err"
  wait $TPID 2>/dev/null
  kill -INT $NPID 2>/dev/null
  for i in $(seq 1 20); do pgrep -x rgbd_odometry >/dev/null || break; sleep 1; done
  pgrep -x rgbd_odometry >/dev/null && { kill -TERM $NPID 2>/dev/null; sleep 3; }
  pgrep -x rgbd_odometry >/dev/null && pkill -KILL -x rgbd_odometry
  sleep 2
  cpu=$(grep -E "rgbd_od" "$OUT/$name.top.log" | awk '{s+=$9; n++} END{if(n) printf "%.1f", s/n; else print "na"}')
  cam=$(grep -E "realsen" "$OUT/$name.top.log" | awk '{s+=$9; n++} END{if(n) printf "%.1f", s/n; else print "na"}')
  lossl=$(grep -c -iE "odometry lost|Not enough inliers|Registration failed|Trial with no guess" "$OUT/$name.node.log")
  dropl=$(grep -c -iE "Dropping|time difference" "$OUT/$name.node.log")
  echo "$name cpu_vo=$cpu cpu_cam=$cam loss_lines=$lossl drop_lines=$dropl $(tr -d '\n' < "$OUT/$name.probe.json")" | tee -a "$OUT/summary.txt"
done
touch "$OUT/DONE"
