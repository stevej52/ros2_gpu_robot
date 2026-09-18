# The GPU stack on JetPack 7.2.1

What is available on the Jetson Orin Nano Super after a JetPack 7.2.1
install, how to get at it from ROS 2 Jazzy, and which option to pick for a
new node. Checked September 2026.

## 1. See what you have

```bash
ros2 run gpu_tools gpu_info        # or python3 -m gpu_tools.probe
```

If `cuda toolkit` says `not found`, the JetPack components are not installed
yet. The ISO install puts Jetson Linux on the drive; the CUDA side is one
meta package away:

```bash
sudo apt update && sudo apt install -y nvidia-jetpack
```

That pulls CUDA 13.2, cuDNN, TensorRT, VPI, Nsight tools and the multimedia
API, all as apt packages from NVIDIA's repository. `nvcc` lands in
`/usr/local/cuda/bin`; add it to `PATH` in `~/.bashrc`:

```bash
export PATH=/usr/local/cuda/bin:$PATH
```

## 2. Power mode

The "Super" part is a power mode. Check and pick the mode before measuring
anything:

```bash
sudo nvpmodel -q              # current mode
sudo nvpmodel -p --verbose    # list of modes; MAXN SUPER is the fastest
sudo nvpmodel -m <n>          # switch (persists across reboots)
sudo jetson_clocks            # pin clocks at maximum until the next reboot
```

## 3. Four ways to use the GPU from a ROS 2 node

| Option | Language | Install | Use it for |
|---|---|---|---|
| CUDA C++ | C++ | `nvidia-jetpack` only | custom kernels, image processing, anything latency critical |
| PyTorch | Python | NVIDIA's JetPack wheels, in a venv | running trained models, quick experiments |
| CuPy | Python | NVIDIA's JetPack wheels, in a venv | NumPy code moved to the GPU |
| Isaac ROS 4.6 | C++ packages, launch files | NVIDIA's apt repo or containers | stereo depth, AprilTag, DNN inference, visual SLAM, ready made |

### CUDA C++

An `ament_cmake` package with CUDA enabled:

```cmake
cmake_minimum_required(VERSION 3.22)
project(my_gpu_node LANGUAGES CXX CUDA)
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(CUDAToolkit REQUIRED)
set(CMAKE_CUDA_ARCHITECTURES 87)          # Orin
add_executable(my_gpu_node src/node.cpp src/kernels.cu)
ament_target_dependencies(my_gpu_node rclcpp sensor_msgs)
target_link_libraries(my_gpu_node CUDA::cudart)
install(TARGETS my_gpu_node DESTINATION lib/${PROJECT_NAME})
ament_package()
```

Orin is compute capability 8.7. Pass `-DCMAKE_CUDA_ARCHITECTURES=87` or set
it as above; leaving it unset builds for a default that may not include
Orin. `colcon build` picks `nvcc` up from `PATH` or `/usr/local/cuda`.

### PyTorch and CuPy (Python)

Ubuntu 24.04 refuses `pip install` into the system Python, and the ROS 2
rule for this robot is "no pip into the system Python" anyway. NVIDIA
publishes PyTorch wheels built for each JetPack release (the plain PyPI
wheel does not use the Jetson GPU). The clean pattern is a venv that can
still see the system's `rclpy`:

```bash
python3 -m venv --system-site-packages ~/.venvs/gpu
source ~/.venvs/gpu/bin/activate
pip install <PyTorch wheel URL for JetPack 7.2 from NVIDIA>
python3 -c "import torch; print(torch.cuda.get_device_name(0))"
```

Take the wheel URL from NVIDIA's "PyTorch for Jetson" page for JetPack 7.x;
it changes with every release, so it is not copied here. CuPy has a similar
build for Jetson.

To run a ROS 2 Python node with the venv's packages, build the workspace
with the venv activated: `colcon build` then writes node scripts that use
the venv interpreter. Alternatively run the module directly:

```bash
source ~/.venvs/gpu/bin/activate
python3 -m gpu_tools.gpu_info_node
```

`gpu_info` shows which interpreter's libraries it found, so it is the quick
check for "am I in the right venv".

### TensorRT

Ships with `nvidia-jetpack`; the Python bindings are the `python3-libnvinfer`
apt package. Build engines on the Jetson itself (an engine is specific to
the GPU and the TensorRT version) and keep them out of git; `.gitignore`
already excludes `*.engine`.

### Isaac ROS 4.6

NVIDIA's accelerated ROS 2 packages, released for ROS 2 Jazzy on JetPack
7.2. They come as apt packages and as containers, and cover the pipelines
that are painful to write by hand: stereo depth, visual SLAM, AprilTag,
image segmentation and detection with TensorRT. Start at
<https://nvidia-isaac-ros.github.io/getting_started/index.html>; the "compute
setup" page has the Jetson steps, including the container tooling. When an
Isaac ROS package does what you need, use it rather than writing a kernel.

## 4. Rules that keep the robot buildable

- The host PC has no Jetson GPU. Every node in this repository must start
  on the PC and either fall back to the CPU or exit with a message that says
  it needs the GPU. Test the launch files on the PC.
- One venv for GPU Python, created the same way on every Jetson, and
  documented in the README of the package that needs it.
- No engines, weights over a few megabytes, or datasets in git. Put a
  download script in the package instead.
- `gpu_info` output goes into every bug report.
