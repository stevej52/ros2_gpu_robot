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

"""The node publishes a latched report (needs rclpy; skipped otherwise)."""

from gpu_tools.gpu_info_node import GpuInfoNode
import rclpy
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile
from std_msgs.msg import String


def test_report_is_published_and_latched():
    rclpy.init()
    try:
        node = GpuInfoNode()
        received = []
        listener = rclpy.create_node('listener')
        qos = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        listener.create_subscription(String, '/gpu_info/report', received.append, qos)
        executor = rclpy.executors.SingleThreadedExecutor()
        executor.add_node(node)
        executor.add_node(listener)
        deadline = node.get_clock().now().nanoseconds + 5 * 10**9
        while not received and node.get_clock().now().nanoseconds < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert received, 'no report received within 5 s'
        assert 'gpu:' in received[0].data
        node.destroy_node()
        listener.destroy_node()
    finally:
        rclpy.shutdown()
