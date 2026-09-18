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
ROS 2 node that publishes the ``gpu_info`` report.

The report is logged once at start-up and published on ``~/report``
(``std_msgs/String``) with transient-local durability, so a tool that
subscribes later still receives it. It is re-published every ``period``
seconds (parameter, default 5.0; 0 publishes once).
"""

from gpu_tools.probe import probe
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile
from std_msgs.msg import String


class GpuInfoNode(Node):
    """Publish what GPU acceleration this machine has."""

    def __init__(self) -> None:
        super().__init__('gpu_info')
        self.declare_parameter('period', 5.0)
        qos = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._publisher = self.create_publisher(String, '~/report', qos)
        self.report = probe()
        for line in self.report.lines():
            self.get_logger().info(line)
        if not self.report.gpu_available:
            self.get_logger().warning(
                'no Python library can see a GPU on this machine; '
                'GPU nodes will fall back or refuse to start')
        self.publish()
        period = float(self.get_parameter('period').value)
        if period > 0:
            self.create_timer(period, self.publish)

    def publish(self) -> None:
        """Send the current report."""
        message = String()
        message.data = '\n'.join(self.report.lines())
        self._publisher.publish(message)


def main(args=None) -> None:
    """Entry point for ``ros2 run gpu_tools gpu_info_node``."""
    rclpy.init(args=args)
    node = GpuInfoNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
