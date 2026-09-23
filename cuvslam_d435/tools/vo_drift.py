import sys, time, math, statistics, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
rclpy.init(); n = Node('vo_drift'); xs=[]; ys=[]; yaws=[]
def cb(m):
    p=m.pose.pose.position; q=m.pose.pose.orientation
    xs.append(p.x); ys.append(p.y); yaws.append(math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)))
n.create_subscription(Odometry, '/vo', cb, qos_profile_sensor_data)
dur=float(sys.argv[1]) if len(sys.argv)>1 else 20; t0=time.monotonic()
while rclpy.ok() and time.monotonic()-t0<dur: rclpy.spin_once(n, timeout_sec=0.2)
if xs:
    print("vo static drift over %.0fs: n=%d  x range %.1f mm  y range %.1f mm  yaw range %.3f deg  x std %.2f mm" % (dur, len(xs), 1000*(max(xs)-min(xs)), 1000*(max(ys)-min(ys)), math.degrees(max(yaws)-min(yaws)), 1000*statistics.pstdev(xs)))
else: print("vo static drift: no /vo messages")
n.destroy_node(); rclpy.shutdown()
