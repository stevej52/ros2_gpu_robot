# GPU roadmap for the RidgeRock robot

What the GPU on the Jetson Orin Nano Super should be used for, in what order,
and what it must not be used for. Drafted 2026-09-18 from the robot's launch
files and configuration in
[jetnano_robot](https://github.com/stevej52/jetnano_robot), checked against
them again on 2026-09-19, and updated with the measured baseline of that day.

## Baseline, 2026-09-19

| Machine | Found | Consequence |
|---|---|---|
| Jetson (Orin Nano Super, Jetson Linux 39.2.1) | `nvidia-jetpack` not installed: no CUDA, cuDNN or TensorRT; `gpu_info` says `gpu: no`; power mode 25 W (mode 1) | nothing below can start until step 0 is done |
| H2-Host (i9-14900HX, Intel graphics) | no GPU, as designed | every node here must launch on it with a CPU path or a clear refusal |

`gpu_tools` builds and runs correctly on both (aarch64 and x86_64), and
`gpu_info --require-gpu` returns exit status 1 on both. apt independently
confirms JetPack 7.2.1 (`nvidia-jetpack` candidate 7.2.1-b49) as the current
release for this kit.

## What runs today, ranked by CPU cost

From `jetnano_bringup/launch/*.launch.py` and `jetnano_navigation/config/*`:

1. **`rtabmap_odom/rgbd_odometry`**, by far the biggest. 640x480 at 30 Hz
   colour plus aligned depth; feature detection, descriptors, matching and
   motion estimation on the CPU, all the time. It is on the critical path:
   the chassis has no wheel encoders, so this node *is* the odometry and has
   no fallback. It runs with `publish_tf: false` and hands its estimate to
   the EKF on `/vo`.
2. **RealSense depth-to-colour alignment.** `align_depth.enable: true` is a
   CPU reprojection at 30 Hz inside `realsense2_camera`, and it exists only
   because `rgbd_odometry` wants registered depth. Change the odometry and
   this cost disappears.
3. **Nav2 planning.** `SmacPlannerHybrid` plus costmaps at 5 Hz local and
   1 Hz global. Moderate, bursty, rarely the bottleneck.
4. **`slam_toolbox`: leave on the CPU.** An A1M8 gives one plane of a few
   thousand points per second; Ceres scan matching on that is small, and the
   transfer to the GPU would likely make it slower. It looks accelerable and
   is not.
5. **EKF, twist_mux, teleop, PCA9685: never.** Microseconds of work, bound by
   I2C and evdev.

## The gap worth noticing

Both costmaps use `observation_sources: scan`. The D435 contributes nothing
to obstacle avoidance: the robot plans around a 2D slice at lidar height and
cannot see a table edge, a step, or anything above or below that plane. On a
rock crawler that is a real limitation, and it is the gap the GPU closes
best.

## Order of work

### 0. Install the JetPack components and set the power mode

On the Jetson, with root:

```bash
sudo apt-get update && sudo apt-get install -y nvidia-jetpack
sudo nvpmodel -m 2        # MAXN_SUPER on this kit (0 = 15 W, 1 = 25 W, 2 = MAXN_SUPER)
```

Then `ros2 run gpu_tools gpu_info` must show the CUDA toolkit and TensorRT
rows populated and `gpu: yes`. Any measurement taken in the 25 W mode
understates the hardware, so set the mode before measuring anything.

### 1. Measure first

Run `tegrastats` (or `jtop`) alongside a full `robot.launch.py` and confirm
that `rgbd_odometry` is the hog. Everything above reasons from configuration,
not from measured numbers. The first code in this repository after
`gpu_tools` is a small load monitor node for exactly this: it samples
`tegrastats` on the Jetson and `/proc` on the PC, publishes CPU, GPU and
memory load as a topic, and needs no root and no CUDA, so it can run today.

### 2. nvblox first, not visual SLAM

[Isaac ROS nvblox](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/index.html)
reconstructs the scene in 3D on the GPU from D435 depth and the robot's pose,
and publishes a 2D costmap for Nav2. It is additive: a new costmap layer,
nothing to un-wire, and it fixes the capability gap above rather than
speeding up something that already works. Its cost in GPU time and memory is
the number that decides whether step 3 fits.

### 3. Then visual SLAM

[Isaac ROS Visual SLAM](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_visual_slam/index.html)
(cuVSLAM) replaces `rgbd_odometry` with GPU stereo visual odometry from the
D435's infrared pair, which also removes the depth alignment cost. Two
things make it a reconfiguration rather than a node swap:

- It wants the raw infrared stereo pair with the projector off, not RGB-D.
  With nvblox wanting projector-on depth at the same time, NVIDIA's pattern
  is emitter alternating with a splitter that sends projector-on frames to
  nvblox and projector-off frames to visual SLAM.
- The D435 has no IMU; the BNO055 is a separate I2C device. Run cuVSLAM in
  stereo-only tracking mode (`enable_imu_fusion: false`) and keep the
  current ownership: it publishes to `/vo` with no transform, and the EKF
  keeps owning `odom -> base_footprint`.

### 4. DNN work last

When the memory left after steps 2 and 3 is known:

- TensorRT object detection on the colour stream: the "find and drive to X"
  class of behaviour.
- Semantic segmentation for traversability. For a rock crawler, what is
  drivable versus what will high-centre you matters more than generic
  obstacle detection; it feeds a Nav2 cost layer.
- Isaac ROS AprilTag for docking and fixed landmarks.
- Isaac ROS ESS (DNN stereo depth) where the D435's own depth fails, in low
  texture or low light.
- A small on-board vision-language model for natural-language commands, if
  the memory ceiling allows it, which it may not.

## Three constraints that will bite

- **Memory is the ceiling, not compute.** The Orin Nano Super has 8 GB shared
  between CPU and GPU. cuVSLAM, nvblox and a DNN will contend, and the
  failure is out-of-memory before it is out-of-compute. Budget memory first.
- **Copies eat the gains.** The win is keeping the image in GPU memory across
  node boundaries (Isaac ROS NITROS type negotiation). A GPU node sandwiched
  between two CPU nodes can be slower than the CPU version: two transfers to
  save one kernel. Accelerate contiguous runs of the pipeline, not isolated
  nodes.
- **The no-source-builds rule.** [gpu-stack.md](gpu-stack.md) commits to apt
  binaries. Getting CUDA into rtabmap itself would need a source build,
  which is why Isaac ROS is the route. Isaac ROS 4.6 targets ROS 2 Jazzy on
  JetPack 7.2, and NVIDIA recommends its own CLI-managed environment for
  installs, with some packages container-first. Before committing to a
  package, check what is installable on the Jetson with
  `apt-cache search isaac-ros` and read that package's page for Jazzy.

## Sources

- The robot: [jetnano_robot](https://github.com/stevej52/jetnano_robot),
  `jetnano_bringup/launch/odometry.launch.py`, `sensors.launch.py`,
  `config/ekf.yaml`, `jetnano_navigation/config/nav2.yaml`,
  `slam_toolbox.yaml`.
- Isaac ROS: [release notes](https://nvidia-isaac-ros.github.io/releases/index.html),
  [getting started](https://nvidia-isaac-ros.github.io/getting_started/index.html),
  [nvblox](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/index.html),
  [visual SLAM with a RealSense camera](https://nvidia-isaac-ros.github.io/concepts/visual_slam/cuvslam/tutorial_realsense.html),
  [nvblox and RealSense emitter strategy](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_nvblox/isaac_ros_nvblox/troubleshooting/troubleshooting_nvblox_realsense.html).
- This repository: [gpu-stack.md](gpu-stack.md) for how CUDA, PyTorch, CuPy,
  TensorRT and Isaac ROS fit together on JetPack 7.
