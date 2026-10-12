"""Does the projector really alternate? Per IR frame: its emitter flag (metadata) and its speckle
(mean |difference| between horizontal neighbours: dots ~16, clean ~0.6 on 2026-09-27)."""
import json, sys, time
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from realsense2_camera_msgs.msg import Metadata

ns = sys.argv[1] if len(sys.argv) > 1 else "/camera/camera"
rclpy.init()
n = rclpy.create_node("speckle_probe")
meta, imgs = {}, []
def key(h): return (h.stamp.sec, h.stamp.nanosec)
def on_meta(m):
    try: meta[key(m.header)] = json.loads(m.json_data).get("frame_emitter_mode")
    except ValueError: pass
def on_img(m):
    a = np.frombuffer(bytes(m.data), np.uint8).reshape(m.height, m.step)[:, :m.width].astype(np.int16)
    imgs.append((key(m.header), float(np.abs(np.diff(a, axis=1)).mean())))
n.create_subscription(Metadata, ns + "/infra1/metadata", on_meta, qos_profile_sensor_data)
n.create_subscription(Image, ns + "/infra1/image_rect_raw", on_img, qos_profile_sensor_data)
end = time.time() + 4.0
while time.time() < end:
    rclpy.spin_once(n, timeout_sec=0.05)
by = {}
for k, s in imgs:
    by.setdefault(meta.get(k, "no-meta"), []).append(s)
print(f"{len(imgs)} frames: " + "; ".join(f"emitter_mode {m}: {len(v)} frames, speckle {np.median(v):.1f} (min {min(v):.1f} max {max(v):.1f})" for m, v in sorted(by.items(), key=str)))
