# ros2_gpu_robot

GPU-accelerated ROS 2 nodes for a robot built around the NVIDIA Jetson Orin
Nano Super. This repository is the home for everything that should run on the
Jetson's GPU: perception, inference, image processing. Actuation lives in
[ros2_pca9685](https://github.com/stevej52/ros2_pca9685), the robot's own ROS 2
stack in [jetnano_robot](https://github.com/stevej52/jetnano_robot), and the
machine setup all of them assume is in
[robot-environment](https://github.com/stevej52/robot-environment).

## Target stack

| Piece | Version | Why |
|---|---|---|
| Jetson Orin Nano Super Developer Kit | JetPack 7.2.1 = Jetson Linux 39.2.1 | current JetPack for the Orin family |
| Ubuntu | 24.04 LTS, on the Jetson and on the host PC | what JetPack 7.2 is built on |
| ROS 2 | Jazzy Jalisco, from apt | LTS for 24.04, also what Isaac ROS 4.6 targets |
| CUDA / cuDNN / TensorRT | 13.2.1 / 9.20 / 10.16.2 | what JetPack 7.2.1 ships |
| Python | 3.12 (system) | what Jazzy on 24.04 uses |

Everything comes from binary packages. Nothing in this repository requires
building CUDA, ROS 2 or a GPU library from source.

## Layout

Each top-level directory is one ROS 2 package. Clone the whole repository
into a workspace and colcon finds them all:

```
ros2_gpu_robot/
  gpu_tools/        gpu_info: what GPU acceleration this machine has; load_monitor: how busy it is
  docs/gpu-stack.md how CUDA, PyTorch, CuPy, TensorRT and Isaac ROS fit together on JetPack 7
  docs/roadmap.md   what the GPU is for on this robot, in what order, and what stays on the CPU
```

## Install and build

```bash
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
git clone https://github.com/stevej52/ros2_gpu_robot.git
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -y
colcon build --symlink-install
source install/setup.bash
```

## First thing to run

`gpu_info` tells you what the machine can do before you write a line of GPU
code. It works without ROS 2 and without a GPU (it then says so):

```bash
ros2 run gpu_tools gpu_info                  # or: python3 -m gpu_tools.probe
ros2 run gpu_tools gpu_info --require-gpu    # exit status 1 if no library sees a GPU
```

Example on a Jetson:

```
host:         orin
machine:      aarch64
os:           Ubuntu 24.04.3 LTS
kernel:       6.8.12-tegra
jetson:       NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super
jetson linux: 39.2.1
jetpack:      7.2.1-b...
cuda toolkit: 13.2 (/usr/local/cuda/bin/nvcc)
torch 2.9.0: Orin
cupy: not installed
tensorrt 10.16.2: available
gpu:          yes
```

The same information is published on a topic by `gpu_info_node`, latched so
that a tool started later still receives it:

```bash
ros2 run gpu_tools gpu_info_node
ros2 topic echo /gpu_info/report
```

## Measure before accelerating

`load_sample` prints how busy the machine is: CPU, GPU, memory, and on a
Jetson the temperatures and power, read from `tegrastats` there and from
`/proc` on a PC (where the GPU column reads `-`). No ROS, CUDA or root
needed. Run it next to the full robot launch to see what is actually loaded:

```bash
ros2 run gpu_tools load_sample --samples 30     # or: python3 -m gpu_tools.load --samples 30
```

```
   1.0s  cpu 41%  gpu 0%  mem 3011/7620MB (40%)  swap 0/3810MB  gpu 45C  cpu 46C  5.0W
   ...
average of 30:  cpu 39%  gpu 0%  mem 3105/7620MB (41%)  swap 0/3810MB  gpu 47C  cpu 48C  5.1W
```

The same numbers go out on `/diagnostics` from `load_monitor`, once a
second by default, with the level raised to WARN when memory passes 90%:

```bash
ros2 run gpu_tools load_monitor
ros2 topic echo /diagnostics
```

## Adding GPU code

Read [docs/gpu-stack.md](docs/gpu-stack.md) first. Short version:

- **CUDA C++** nodes: `ament_cmake` packages with `enable_language(CUDA)`;
  the toolkit comes from `sudo apt install nvidia-jetpack`.
- **Python** nodes: PyTorch or CuPy from NVIDIA's JetPack wheels, in a venv
  created with `--system-site-packages` so `rclpy` stays visible.
- **Isaac ROS 4.6**: NVIDIA's accelerated perception packages for Jazzy on
  JetPack 7.2, when a ready-made pipeline fits.

Keep the host PC in mind: a node that needs the GPU should degrade to a
clear error, or a CPU path, when run on a machine without one, so the whole
graph can still be launched on the PC with the Jetson's nodes remapped or
disabled.

## License

Apache License 2.0, see [LICENSE](LICENSE).
