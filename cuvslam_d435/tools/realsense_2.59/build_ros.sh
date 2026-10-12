#!/bin/bash
# realsense-ros 4.59.1 against /workspaces/isaac_ros-dev/rs259/prefix (librealsense 2.59.1), overlay ws rs259/ws.
set -e
R=/workspaces/isaac_ros-dev/rs259
until grep -q BUILD-DONE $R/build.log 2>/dev/null; do grep -q "Error\b\|\*\*\* \[" $R/build.log && { echo "librealsense build failed"; exit 1; }; sleep 30; done
mkdir -p $R/ws/src && cd $R/ws/src
[ -d realsense-ros ] || { curl -sL https://github.com/realsenseai/realsense-ros/archive/refs/tags/4.59.1.tar.gz | tar xz && mv realsense-ros-4.59.1 realsense-ros; }
cd $R/ws
source /opt/ros/jazzy/setup.bash
export CMAKE_PREFIX_PATH=$R/prefix:$CMAKE_PREFIX_PATH
nice -n 15 colcon build --parallel-workers 2 --cmake-args -DCMAKE_BUILD_TYPE=Release -Drealsense2_DIR=$R/prefix/lib/cmake/realsense2 -DBUILD_TESTING=OFF
echo ROS-DONE
