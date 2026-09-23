#!/usr/bin/env python3
"""Measure visual odometry for N seconds: /vo rate and jitter, /odom_info quality, colour brightness.

Prints one JSON object. Run while rgbd_odometry (or any node publishing /vo and /odom_info) is up.
"""
import json, statistics, sys, time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image
from rtabmap_msgs.msg import OdomInfo


class Probe(Node):
    def __init__(self, duration):
        super().__init__('vo_probe')
        self.duration = duration
        self.t0 = time.monotonic()
        self.vo_t, self.info, self.bright, self.img_n = [], [], [], 0
        self.create_subscription(Odometry, '/vo', self.on_vo, qos_profile_sensor_data)
        self.create_subscription(OdomInfo, '/odom_info', self.on_info, qos_profile_sensor_data)
        self.create_subscription(Image, '/camera/camera/color/image_raw', self.on_img, qos_profile_sensor_data)

    def on_vo(self, m):
        self.vo_t.append(time.monotonic())

    def on_info(self, m):
        self.info.append((bool(m.lost), m.features, m.matches, m.inliers, float(m.time_estimation)))

    def on_img(self, m):
        self.img_n += 1
        if self.img_n % 30 == 1:
            d = m.data
            step = max(1, len(d) // 20000)
            s = d[::step]
            self.bright.append(sum(s) / len(s))

    def report(self):
        t_end = time.monotonic()
        settle = self.t0 + 5.0
        vo = [t for t in self.vo_t if t > settle]
        span = t_end - settle
        gaps = [b - a for a, b in zip(vo, vo[1:])]
        infos = self.info
        lost = sum(1 for i in infos if i[0])
        ok = [i for i in infos if not i[0]]
        def mean(xs): return round(statistics.fmean(xs), 1) if xs else None
        out = {
            'duration_s': round(t_end - self.t0, 1),
            'vo_hz': round(len(vo) / span, 2) if span > 0 else None,
            'vo_gap_ms_median': round(1000 * statistics.median(gaps), 1) if gaps else None,
            'vo_gap_ms_max': round(1000 * max(gaps), 1) if gaps else None,
            'odom_info_msgs': len(infos),
            'lost_msgs': lost,
            'features_mean': mean([i[1] for i in ok]),
            'matches_mean': mean([i[2] for i in ok]),
            'inliers_mean': mean([i[3] for i in ok]),
            'inliers_min': min([i[3] for i in ok]) if ok else None,
            'time_est_ms_mean': mean([1000 * i[4] for i in ok]),
            'time_est_ms_max': round(1000 * max(i[4] for i in ok), 1) if ok else None,
            'colour_frames_seen': self.img_n,
            'colour_brightness_mean': mean(self.bright),
        }
        return out


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    rclpy.init()
    node = Probe(duration)
    while rclpy.ok() and time.monotonic() - node.t0 < duration:
        rclpy.spin_once(node, timeout_sec=0.2)
    print(json.dumps(node.report()))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
