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

"""The load monitor publishes diagnostics (needs rclpy; skipped otherwise)."""

from diagnostic_msgs.msg import DiagnosticArray
from gpu_tools.load_monitor_node import LoadMonitorNode
import rclpy
from rclpy.parameter import Parameter


def test_load_is_published_as_diagnostics():
    rclpy.init()
    try:
        node = LoadMonitorNode()
        node.set_parameters([Parameter('source', Parameter.Type.STRING, 'proc')])
        received = []
        listener = rclpy.create_node('listener')
        listener.create_subscription(DiagnosticArray, '/diagnostics', received.append, 10)
        executor = rclpy.executors.SingleThreadedExecutor()
        executor.add_node(node)
        executor.add_node(listener)
        deadline = node.get_clock().now().nanoseconds + 5 * 10**9
        while not received and node.get_clock().now().nanoseconds < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert received, 'no diagnostics received within 5 s'
        status = received[0].status[0]
        assert status.name == 'gpu_tools/load'
        keys = {value.key for value in status.values}
        assert {'cpu_percent', 'gpu_percent', 'mem_percent'} <= keys
        node.destroy_node()
        listener.destroy_node()
    finally:
        rclpy.shutdown()
