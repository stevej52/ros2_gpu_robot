#!/bin/bash
# librealsense 2.59.1 for the isaac_vo container, beside NVIDIA's 2.56.3 in /usr/local (2026-10-12).
# Same backend as theirs (RSUSB, no CUDA); usage statistics compiled out; no update checks.
set -e
cd /workspaces/isaac_ros-dev/rs259
[ -d librealsense-2.59.1 ] || { curl -sL https://github.com/realsenseai/librealsense/archive/refs/tags/v2.59.1.tar.gz | tar xz; }
mkdir -p build && cd build
cmake ../librealsense-2.59.1 -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/workspaces/isaac_ros-dev/rs259/prefix \
  -DFORCE_RSUSB_BACKEND=ON -DBUILD_WITH_CUDA=OFF -DENABLE_STATS=OFF -DCHECK_FOR_UPDATES=OFF \
  -DBUILD_EXAMPLES=OFF -DBUILD_GRAPHICAL_EXAMPLES=OFF -DBUILD_TOOLS=ON -DBUILD_UNIT_TESTS=OFF \
  -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_WITH_OPENMP=OFF
nice -n 15 make -j4
make install
echo BUILD-DONE
