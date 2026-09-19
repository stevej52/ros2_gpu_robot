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
ROS 2 node that publishes the machine's load on ``/diagnostics``.

Every ``period`` seconds (parameter, default 1.0) it publishes one
``diagnostic_msgs/DiagnosticArray`` with a status named ``gpu_tools/load``
whose values are the fields of :class:`gpu_tools.load.LoadSample`: CPU, GPU
and memory use, temperatures and power on a Jetson. The level turns to WARN
when memory use passes ``memory_warn_percent`` (default 90), because on an
8 GB Jetson memory runs out before compute does.

``source`` (``auto``, ``tegrastats`` or ``proc``) picks where the numbers
come from; ``log_every`` (default 10, 0 for never) prints a summary line to
the log every that many samples.
"""

import socket

from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from gpu_tools.load import make_sampler
import rclpy
from rclpy.node import Node


class LoadMonitorNode(Node):
    """Publish CPU, GPU and memory load as diagnostics."""

    def __init__(self) -> None:
        super().__init__('load_monitor')
        self.declare_parameter('period', 1.0)
        self.declare_parameter('source', 'auto')
        self.declare_parameter('log_every', 10)
        self.declare_parameter('memory_warn_percent', 90.0)
        period = float(self.get_parameter('period').value)
        source = str(self.get_parameter('source').value)
        self._log_every = int(self.get_parameter('log_every').value)
        self._memory_warn = float(self.get_parameter('memory_warn_percent').value)
        self._hostname = socket.gethostname()
        self._count = 0
        self._sampler = make_sampler(source, interval_ms=max(100, int(period * 1000)))
        self._publisher = self.create_publisher(DiagnosticArray, '/diagnostics', 10)
        self.get_logger().info(f'reading load from {type(self._sampler).__name__} '
                               f'every {period:g} s')
        self.create_timer(period, self.tick)

    def tick(self) -> None:
        """Take one sample and publish it."""
        sample = self._sampler.sample()
        if sample is None:          # tegrastats has not produced a line yet
            return
        status = DiagnosticStatus()
        status.name = 'gpu_tools/load'
        status.hardware_id = self._hostname
        status.message = sample.summary()
        status.level = DiagnosticStatus.OK
        if sample.mem_percent is not None and sample.mem_percent >= self._memory_warn:
            status.level = DiagnosticStatus.WARN
            status.message = f'memory {sample.mem_percent:.0f}% full; ' + status.message
        status.values = [KeyValue(key=key, value=value) for key, value in sample.key_values()]
        message = DiagnosticArray()
        message.header.stamp = self.get_clock().now().to_msg()
        message.status = [status]
        self._publisher.publish(message)
        self._count += 1
        if self._log_every and self._count % self._log_every == 0:
            self.get_logger().info(status.message)

    def destroy_node(self) -> bool:
        """Stop the sampler with the node."""
        self._sampler.close()
        return super().destroy_node()


def main(args=None) -> None:
    """Entry point for ``ros2 run gpu_tools load_monitor``."""
    rclpy.init(args=args)
    node = LoadMonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
