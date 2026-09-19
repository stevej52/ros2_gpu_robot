# Copyright 2026 stevej52
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Publish a synthetic RGB-D stream on the topics the RealSense driver uses.

This stands in for a D435 so the odometry half of the robot can be run,
profiled and regression-tested on a bench with no camera attached. The topic
names and encodings match ``realsense2_camera`` with ``align_depth.enable``
set, which is how ``jetnano_bringup/launch/sensors.launch.py`` configures it,
so ``odometry.launch.py`` runs against this unmodified:

    /camera/camera/color/image_raw                  rgb8
    /camera/camera/color/camera_info                CameraInfo
    /camera/camera/aligned_depth_to_color/image_raw 16UC1, millimetres

Frames are rendered once at start-up into a ring buffer and then published as
raw bytes, so the publisher costs almost nothing at run time. That matters:
this node exists in order to measure another node, and a generator that burned
a core of its own would corrupt the number it is meant to produce. Measure
this node alone first, then add the node under test and subtract.

Colour and depth carry the SAME timestamp, so the odometry's synchroniser
pairs them without slop.
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from sensor_msgs.msg import CameraInfo, Image

from synthetic_camera.scene import CameraModel, CorridorScene, build_ring

COLOUR_TOPIC = '/camera/camera/color/image_raw'
INFO_TOPIC = '/camera/camera/color/camera_info'
DEPTH_TOPIC = '/camera/camera/aligned_depth_to_color/image_raw'


class SyntheticRgbdPublisher(Node):
    """Publish a moving, textured corridor as an RGB-D pair."""

    def __init__(self) -> None:
        """Declare parameters, pre-render the frames, then start the timer."""
        super().__init__('synthetic_rgbd')
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30.0)
        self.declare_parameter('frames', 30)
        self.declare_parameter('speed', 0.02)
        self.declare_parameter('frame_id', 'camera_color_optical_frame')
        self.declare_parameter('seed', 20260919)

        width = int(self.get_parameter('width').value)
        height = int(self.get_parameter('height').value)
        fps = float(self.get_parameter('fps').value)
        frames = max(1, int(self.get_parameter('frames').value))
        self._frame_id = str(self.get_parameter('frame_id').value)

        self._camera = CameraModel(width=width, height=height)
        scene = CorridorScene(
            camera=self._camera,
            speed=float(self.get_parameter('speed').value),
            seed=int(self.get_parameter('seed').value))

        self.get_logger().info(
            f'rendering {frames} frames at {width}x{height}, this takes a moment')
        self._colours, self._depth = build_ring(scene, frames)
        megabytes = (len(self._colours) * len(self._colours[0]) + len(self._depth)) / 1e6
        self.get_logger().info(f'ring buffer ready, {megabytes:.0f} MB resident')

        sensor_qos = QoSPresetProfiles.SENSOR_DATA.value
        self._colour_pub = self.create_publisher(Image, COLOUR_TOPIC, sensor_qos)
        self._depth_pub = self.create_publisher(Image, DEPTH_TOPIC, sensor_qos)
        self._info_pub = self.create_publisher(CameraInfo, INFO_TOPIC, sensor_qos)

        self._index = 0
        self._published = 0
        self.create_timer(1.0 / fps, self.publish_frame)
        self.create_timer(5.0, self._report)
        self.get_logger().info(f'publishing {COLOUR_TOPIC} and {DEPTH_TOPIC} at {fps:g} Hz')

    def _image(self, stamp, encoding: str, step: int, data: bytes) -> Image:
        """Wrap already-rendered bytes in an Image without copying pixels."""
        message = Image()
        message.header.stamp = stamp
        message.header.frame_id = self._frame_id
        message.height = self._camera.height
        message.width = self._camera.width
        message.encoding = encoding
        message.is_bigendian = 0
        message.step = step
        message.data = data
        return message

    def _camera_info(self, stamp) -> CameraInfo:
        """CameraInfo matching the projection the scene was rendered with."""
        info = CameraInfo()
        info.header.stamp = stamp
        info.header.frame_id = self._frame_id
        info.height = self._camera.height
        info.width = self._camera.width
        info.distortion_model = 'plumb_bob'
        info.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        info.k = self._camera.k_matrix()
        info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        info.p = self._camera.p_matrix()
        return info

    def publish_frame(self) -> None:
        """Send the next colour frame, its depth and its CameraInfo."""
        stamp = self.get_clock().now().to_msg()
        width = self._camera.width
        self._colour_pub.publish(
            self._image(stamp, 'rgb8', width * 3, self._colours[self._index]))
        self._depth_pub.publish(
            self._image(stamp, '16UC1', width * 2, self._depth))
        self._info_pub.publish(self._camera_info(stamp))
        self._index = (self._index + 1) % len(self._colours)
        self._published += 1

    def _report(self) -> None:
        """Log how many frames have gone out, so a stall is visible."""
        self.get_logger().info(f'{self._published} frames published')


def main(args=None) -> None:
    """Entry point for ``ros2 run synthetic_camera synthetic_rgbd``."""
    rclpy.init(args=args)
    node = SyntheticRgbdPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
