# GPU visual odometry for the RidgeRock: Isaac ROS 4.6 cuVSLAM on the D435's infrared pair

The robot's odometry used to come from rtabmap `rgbd_odometry` on the CPU: about 10 Hz
out of a 30 Hz camera, on 85 % of one core, because the node processes frames in a single
thread and drops what arrives while it is busy. This directory replaces that node with
NVIDIA's cuVSLAM (Isaac ROS Visual SLAM 4.6), run in stereo mode on the D435's two
infrared cameras, inside NVIDIA's own container. Measured on the bench 2026-09-23:

| Odometry | IR profile | `/vo` rate | spacing median / max | its CPU (one core = 100 %) | camera driver CPU | GPU |
|---|---|---|---|---|---|---|
| rtabmap `rgbd_odometry` (colour + aligned depth 640x480x30) | - | 10 Hz | 100 ms / - | 85 % | 39-54 % | 0 % |
| cuVSLAM stereo | 640x360x60, projector off | 59.4 Hz | 16.7 / 35 ms | 23 % | 22 % | 5 % |
| **cuVSLAM stereo** | **640x360x90, projector off** | **89.2 Hz** | **11.1 / 23 ms** | 31 % | 29 % | 5 % |
| cuVSLAM stereo | 848x480x60, projector off | 55.8 Hz | 16.7 / 100 ms | 26 % | 27 % | 6 % |

Static-scene drift over 20 s in dawn light (IR mean 42-56 / 255): 2-6 mm and 0.1-0.3 deg
in every configuration. The 848x480 profile is not faster - the larger frames stall the
stream (hundreds of "delta above threshold" warnings) - so 640x360 at 90 fps is the one to
run. A 3-hour soak at 90 Hz held 90.0 Hz with no memory growth (RSS 575 -> 585 MB).
The whole system with cuVSLAM, the lidar, IMU and EKF up sits at about 1.9 GB RAM.

Tracking under motion has NOT been measured yet - the robot was parked. First job: the
one-metre hand slide from `jetnano_robot/docs/bench-calibration-2026-09-21.md` with
cuVSLAM running, compared against rtabmap's 12 cm / 3.8 deg.

## Why a container, and why this is allowed

Isaac ROS 4.6.0 (2026-08-18) is the release that added Jetson Orin + JetPack 7.2 + ROS 2
Jazzy, and it is the **last** Jazzy release: 5.0.0 (2026-09-21) moved to ROS 2 Lyrical and
renamed the package `isaac_ros_cuvslam`. Everything here is pinned to the `release-4.6`
apt channel and the `/v/release-4.6/` docs.

NVIDIA ships cuVSLAM as an apt package (`ros-jazzy-isaac-ros-visual-slam`) but pins its own
RealSense driver: librealsense 2.56.3 built with the RSUSB (libusb) backend and realsense-ros
4.56.3, compiled inside its image. Running that in Docker means the host keeps its apt
`ros-jazzy-realsense2-camera` 4.58 and nothing on the Jazzy stack changes - the source build
is NVIDIA's, inside NVIDIA's container, which is the "deliberate exception" the house rule
allows. The venv and bare-metal modes of the Isaac ROS CLI remove the host OpenCV packages
and were not used.

The host kernel does NOT need patching: the stock JetPack 7.2 `uvcvideo` streams the
D435's Y8 infrared pair fine (verified in every configuration on 2026-09-23; the 2026-09-22
"IR streams stall depth" finding was a wedged camera that `initial_reset` fixes). The RSUSB
driver in the container talks to the camera over libusb and simply bypasses it.

## Host setup (done on the Orin 2026-09-23)

```bash
# Isaac ROS 4.6 apt repository and CLI
curl -fsSL https://isaac.download.nvidia.com/isaac-ros/repos.key | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-isaac-ros.gpg
echo "deb [signed-by=/usr/share/keyrings/nvidia-isaac-ros.gpg] https://isaac.download.nvidia.com/isaac-ros/release-4.6 noble-jetpack main" | sudo tee /etc/apt/sources.list.d/nvidia-isaac-ros-4.6.list
sudo apt-get update && sudo apt-get install -y isaac-ros-cli      # 2.5.0
sudo usermod -aG docker $USER                                      # docker + nvidia-container-toolkit come with nvidia-jetpack
echo 'export ISAAC_ROS_WS=${HOME}/workspaces/isaac_ros-dev/' >> ~/.bashrc
mkdir -p ~/workspaces/isaac_ros-dev/src
sudo isaac-ros init docker --yes
cp isaac-ros-cli-config.yaml ~/.config/isaac-ros-cli/config.yaml   # enables the 'realsense' image layer
isaac-ros activate --build-local --build-only                      # 1 h 35 min on the Orin, 18.7 GB
```

The image is `cached_isaac_run_dev_image_local:latest`. cuVSLAM was installed inside once
and the result committed as `isaac_vo:4.6` so it survives container restarts:

```bash
docker exec -u root isaac_vo bash -c 'apt-get update && apt-get install -y ros-jazzy-isaac-ros-visual-slam'
docker commit isaac_vo isaac_vo:4.6
```

## Running it

The container is started detached with the same flags the CLI would use, minus `--pid=host`
(with it, a `pkill` inside the container reaches the host's launches):

```bash
docker run -d --privileged --network host --ipc host --gpus all \
  -e ROS_DOMAIN_ID=7 -e ISAAC_ROS_WS=/workspaces/isaac_ros-dev \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e HOST_USER_UID=$(id -u) -e HOST_USER_GID=$(id -g) -e USER=$USER \
  -v $HOME/workspaces/isaac_ros-dev:/workspaces/isaac_ros-dev -v /dev/bus/usb:/dev/bus/usb \
  --workdir /workspaces/isaac_ros-dev --entrypoint /usr/local/bin/scripts/workspace-entrypoint.sh \
  --name isaac_vo isaac_vo:4.6 sleep infinity
```

The camera can have one owner: stop the host's camera launch first
(`sensors.launch.py use_lidar:=false use_imu:=false` runs it on its own, PID in
`~/camera.pid`). Then:

```bash
docker exec -u root -e FASTRTPS_DEFAULT_PROFILES_FILE=/workspaces/isaac_ros-dev/fastdds_udp_only.xml isaac_vo \
  bash -c 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=7; \
           exec ros2 launch /workspaces/isaac_ros-dev/cuvslam_d435_stereo.launch.py infra_profile:=640,360,90 image_jitter_threshold_ms:=12'
```

`cuvslam_d435_stereo.launch.py` (copy it into `$ISAAC_ROS_WS`) is NVIDIA's RealSense
example with the IMU parts removed and the node run as pure odometry: `tracking_mode 0`
(stereo), `enable_localization_n_mapping false`, both TF broadcasters off, output remapped
to `/vo`. `robot_localization` keeps owning `odom -> base_footprint` and `ekf.yaml` is
unchanged; the host EKF is started alone with `odometry.launch.py use_visual_odometry:=false`.
Arguments: `infra_profile` (640,360,60 default; 640,360,90 recommended),
`image_jitter_threshold_ms` (19 for 60 fps, 12 for 90), `emitter` (0; 1 only for load tests
on a static bench - the projector's dot pattern moves with the camera), `base_frame`
(base_link; needs the URDF's TF to the camera, which the host publishes), `ground_constraint`.

`tools/cuvslam_run.sh NAME PROFILE EMITTER JITTER [SECONDS]` restarts the launch with a
profile and records rate, spacing, CPU, GPU and RAM (`tools/vo_probe.py`, `top`,
`tegrastats`); `tools/vo_drift.py` measures static drift; `tools/ir_brightness.py` reports
the IR scene brightness. `tools/vo_sweep.sh` is the rtabmap parameter sweep used for the
CPU baseline.

## The DDS trap

The container's nodes run as root. Fast DDS on one host uses shared memory, and the
segments root creates in `/dev/shm` cannot be opened by the host user, so the host sees
the publisher in `ros2 topic info` but never receives a message. `fastdds_udp_only.xml`
makes the container's participants UDP-only (set `FASTRTPS_DEFAULT_PROFILES_FILE` for
every process in the container); the host side needs nothing. Running the container nodes
as uid 1000 instead loses the `video`/`render` groups (`docker exec` has no `--group-add`)
and CUDA then fails with "no CUDA-capable device".

## Known deviations from NVIDIA's pins

- D435 firmware 5.12.10 on this camera; Isaac ROS pins 5.16.0.1. Not updated.
- The D435 (no IMU) is not in NVIDIA's D455/D435i support table; stereo mode is what the
  tutorial itself prescribes for it, and it works.
- The host camera launch and the container's driver are different librealsense versions
  (2.58.4 V4L2 vs 2.56.3 RSUSB); they never run at the same time.

## Not done yet

- Tracking under motion, and on the rocks. cuVSLAM's `enable_ground_constraint_in_odometry`
  is off; try it only on flat floors.
- nvblox (roadmap step 2) can now follow: same container, `ros-jazzy-isaac-ros-nvblox`
  4.6.0 resolves from the same repo, depth + colour with the projector on, pose from the
  EKF's TF.
- A systemd unit or launch wrapper so the container and its launch come up with the robot.
