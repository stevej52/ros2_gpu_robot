import sys, time, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
rclpy.init(); n = Node('ir_brightness'); vals = []
def cb(m):
    d = m.data; step = max(1, len(d)//20000); s = d[::step]; vals.append(sum(s)/len(s))
n.create_subscription(Image, '/camera/infra1/image_rect_raw', cb, qos_profile_sensor_data)
t0 = time.monotonic()
while rclpy.ok() and time.monotonic()-t0 < 6 and len(vals) < 40: rclpy.spin_once(n, timeout_sec=0.2)
print("ir_brightness_mean_0_255: %.1f over %d frames" % (sum(vals)/len(vals) if vals else -1, len(vals)))
n.destroy_node(); rclpy.shutdown()
