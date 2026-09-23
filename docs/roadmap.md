# GPU roadmap for the RidgeRock robot

What the GPU on the Jetson Orin Nano Super should be used for, in what order,
and what it must not be used for. Drafted 2026-09-18 from the robot's launch
files and configuration in
[jetnano_robot](https://github.com/stevej52/jetnano_robot), checked against
them again on 2026-09-19, and updated with the measured baseline of that day.

## Baseline, 2026-09-19

| Machine | Found | Consequence |
|---|---|---|
| Jetson (Orin Nano Super, Jetson Linux 39.2.1) | `nvidia-jetpack` not installed: no CUDA, cuDNN or TensorRT; `gpu_info` says `gpu: no`; power mode 25 W (mode 1) | nothing below can start until step 0 is done - **done 2026-09-21**: `nvidia-jetpack 7.2.1-b49` (CUDA 13.2, cuDNN 9.20, TensorRT 10.16), MAXN_SUPER, `gpu_info` says `gpu: yes` |
| H2-Host (i9-14900HX, Intel graphics) | no GPU, as designed | every node here must launch on it with a CPU path or a clear refusal |

`gpu_tools` builds and runs correctly on both (aarch64 and x86_64), and
`gpu_info --require-gpu` returns exit status 1 on both. apt independently
confirms JetPack 7.2.1 (`nvidia-jetpack` candidate 7.2.1-b49) as the current
release for this kit.

## Measured on the bench, 2026-09-19 (25 W mode, CPU only)

Taken on the Jetson with `load_sample` and `top`, with no D435 attached: the
`synthetic_camera` package stood in for it, publishing a moving, textured
corridor on the RealSense topics so `odometry.launch.py` ran unmodified.
The stand-in's own cost is listed so it can be subtracted.

| Process | CPU (one core = 100%) | Memory |
|---|---|---|
| `rgbd_odometry`, 640x480 offered at about 28 Hz | 78.7% | 190 MB |
| `synthetic_rgbd` (the stand-in camera; subtract) | 9.0% | 114 MB |
| `slam_toolbox` (measured separately, lidar only) | 7.4% | 98 MB |
| `ekf_node` | 2.0% | 38 MB |
| `robot_state_publisher`, `joint_state_publisher` | 1 to 2% each | |

- **Throughput**: about 28 Hz offered, 10.8 Hz of `/vo` out. About 60% of
  the frames are dropped while most of one core is busy.
- **System**: 905 MB idle, 1272 MB with sensors, odometry and SLAM up, so
  about 6.2 GB free. That is the memory budget for steps 2 to 4.
- **Power**: visual odometry alone adds 1.03 W (5.46 W to 6.49 W).
- **GPU**: 0% throughout, as expected with no CUDA installed.

What it settles: `rgbd_odometry` is about ten times `slam_toolbox` and
larger than everything else on the robot combined, so it stays the GPU
target. It is not just expensive, it is not keeping up: on a chassis with no
wheel encoders every dropped frame is a larger jump for the only odometry
source. Leaving `slam_toolbox` on the CPU is confirmed. Two things remain to
measure: the same run in MAXN_SUPER after step 0, and the real D435 in place
of the stand-in. Tracking robustness on real hardware is unmeasured; see
the note below.

How the stand-in was validated: its first version looped the pre-rendered
frames straight from the last back to the first, a teleport to the
odometry once a second. An A/B on the Jetson under identical conditions
(60 s each) showed 146 tracking losses, 10.0 Hz and 95.5% of a core with
that version against 1 loss, 10.8 Hz and 78.7% with the forward-and-back
playback the package has now. The difference was the odometry re-detecting
features from scratch after every jump, so the earlier, higher figure was
an artifact of the stand-in, not a property of rtabmap. Method note from
the same session: a run where the camera silently fails to publish looks
like a perfect result (zero losses, 1% CPU). Before trusting a zero, check
that the camera topics are flowing and that the odometry's CPU is
non-trivial.

Worth testing on real hardware: rtabmap warned about a 33 ms gap between
colour and depth stamps. The stand-in stamps them identically, so that is
the approximate synchroniser pairing across dropped frames. A real D435 with
aligned depth also carries the colour stamp, so `approx_sync: false` in
`odometry.launch.py` may remove a class of bad pairings. Test before
changing.

## Measured again: MAXN_SUPER (2026-09-21) and the real D435 (2026-09-22)

Both follow-ups from step 1 are done.

**MAXN_SUPER, same stand-in run.** `/vo` went 10.8 to 9.9 Hz - unchanged
within noise - while `rgbd_odometry` fell only from 78.7 % to 73.1 % of a
core, with the load sitting on one core throughout. `rgbd_odometry` is
effectively single-threaded, so more cores and more clock do not buy
frames; whatever caps it near 10 Hz is not raw CPU speed. That is the
strongest argument yet for replacing it (step 3) rather than tuning it.

**The real D435, robot parked on a tile floor, MAXN_SUPER.**

| | |
|---|---|
| `/vo` | ~10 Hz (9.9 over 30 s) |
| tracking | 810 features, 508 matches, 357 inliers, 67 ms per estimate, never lost |
| `rgbd_odometry` | 84-88 % of one core |
| `realsense2_camera` | 39-54 % of a core: depth-to-colour alignment plus stamp sync |
| bno055 / ekf / rplidar | 12-15 % / 5-6 % / 1 % |
| system | 27-39 % of six cores, 6.4-7.0 W, GPU 0 %, 1.17 GB used |

So the stand-in was honest: the real camera costs the same core and gives
the same ~10 Hz. The alignment cost the roadmap guessed at (below) is real
and visible - it is most of the RealSense node's share. On the stamp
question above: the fix was on the driver side, `enable_sync` in
`sensors.launch.py`, which cut rtabmap's "time difference is high" drops
from ~100 to ~20 a minute (colour settles at 25 Hz); `approx_sync: false`
is still untested. Record of the session and the two launch-file fixes it
took (`base_frame_id`, IR streams off): jetnano_robot
`docs/bench-calibration-2026-09-21.md`.

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

**Done 2026-09-21.** Note that `nvpmodel.service` fails at boot on this
kit (exit 234) yet the persisted MAXN_SUPER mode is applied regardless -
verified on a cold boot with `nvpmodel -q`.

### 1. Measure first

Done: the CPU side with the stand-in (the first table), again in
MAXN_SUPER, and with the real D435 (the second table). Keep `load_sample
--samples 60` as the ruler for every step below, and compare against
those tables. Tracking under motion, first sample (robot slid a metre and
back by hand on a plain tile floor): tracked throughout, one single-frame
loss, ~12 cm and 3.8 deg of closed-loop error over 1.7 m, inliers down to
90-200 from ~340 at rest. Rough ground under power is still unmeasured.

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
