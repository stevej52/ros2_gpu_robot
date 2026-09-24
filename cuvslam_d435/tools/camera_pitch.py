#!/usr/bin/env python3
# Copyright 2026 stevej52
# Licensed under the Apache License, Version 2.0. See LICENSE.
"""Measure the camera's pitch, roll and height above the floor from its depth image.

    ros2 run --prefix '' python3 camera_pitch.py            # or just: python3 camera_pitch.py
    python3 camera_pitch.py --depth /camera/depth/image_rect_raw --seconds 5

Put the robot on a flat floor with a metre or two of clear floor in front of
it. This collects depth frames, turns them into points in the camera's optical
frame, finds the dominant plane below the camera (RANSAC, then a least-squares
refit on the inliers), and prints the camera's pitch and roll relative to that
floor and the lens height - the numbers jetnano.urdf.xacro wants for
camera_rpy and camera_xyz (z = height - wheel_radius). Sign convention is
REP-103 / URDF: positive pitch points the camera DOWN.

Works with either camera driver: the host's aligned depth or the container's
depth (the splitter's projector-on frames are the cleanest:
/camera/realsense_splitter_node/output/depth). 16UC1 millimetres or 32FC1 metres.
"""

import argparse
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image


def fit_plane(points: np.ndarray):
    """Least-squares plane through points: unit normal n and offset d, n.p + d = 0."""
    centroid = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vt[-1]
    return normal, -float(normal @ centroid)


def ransac_floor(points: np.ndarray, threshold=0.01, iterations=300, seed=1):
    """The plane with the most points within `threshold`, among random triples."""
    rng = np.random.default_rng(seed)
    best = (0, None)
    n = len(points)
    for _ in range(iterations):
        sample = points[rng.choice(n, 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal /= norm
        d = -float(normal @ sample[0])
        inliers = np.abs(points @ normal + d) < threshold
        count = int(inliers.sum())
        if count > best[0]:
            best = (count, inliers)
    return best[1]


class Collector(Node):

    def __init__(self, depth_topic, info_topic, seconds):
        super().__init__('camera_pitch')
        self.info = None
        self.frames = []
        self.deadline = time.monotonic() + seconds
        self.create_subscription(CameraInfo, info_topic, self._on_info, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self._on_depth, qos_profile_sensor_data)

    def _on_info(self, msg):
        self.info = msg

    def _on_depth(self, msg):
        if msg.encoding == '16UC1':
            depth = np.frombuffer(msg.data, np.uint16).reshape(msg.height, msg.width).astype(np.float32) / 1000.0
        elif msg.encoding == '32FC1':
            depth = np.frombuffer(msg.data, np.float32).reshape(msg.height, msg.width).copy()
        else:
            self.get_logger().error(f'unexpected depth encoding {msg.encoding}')
            return
        self.frames.append(depth)

    def done(self):
        return time.monotonic() > self.deadline and self.info is not None and len(self.frames) >= 3


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--depth', default='/camera/realsense_splitter_node/output/depth')
    parser.add_argument('--info', default='/camera/depth/camera_info')
    parser.add_argument('--seconds', type=float, default=4.0)
    parser.add_argument('--max-range', type=float, default=3.0)
    parser.add_argument('--wheel-radius', type=float, default=0.065)
    args = parser.parse_args()

    rclpy.init()
    node = Collector(args.depth, args.info, args.seconds)
    while rclpy.ok() and not node.done():
        rclpy.spin_once(node, timeout_sec=0.2)
        if time.monotonic() > node.deadline + 10:
            print(f'no data: {len(node.frames)} depth frames, camera_info {"yes" if node.info else "no"}')
            return 1
    info = node.info
    fx, fy, cx, cy = info.k[0], info.k[4], info.k[2], info.k[5]

    # Median over the frames (kills the projector's flicker and stereo noise),
    # then every valid pixel in range as a point in the optical frame
    # (x right, y down, z forward).
    depth = np.median(np.stack(node.frames), axis=0)
    h, w = depth.shape
    v, u = np.mgrid[0:h, 0:w]
    valid = (depth > 0.2) & (depth < args.max_range)
    z = depth[valid]
    x = (u[valid] - cx) * z / fx
    y = (v[valid] - cy) * z / fy
    points = np.column_stack([x, y, z]).astype(np.float64)
    # Only the lower half of the image, and only points below the lens: the
    # floor is there, walls and furniture mostly are not.
    keep = (v[valid] > h * 0.4) & (y > 0.05)
    points = points[keep]
    if len(points) < 500:
        print(f'not enough floor points ({len(points)}); is there clear floor in front of the camera?')
        return 1
    if len(points) > 40000:
        points = points[np.random.default_rng(0).choice(len(points), 40000, replace=False)]

    inliers = ransac_floor(points)
    normal, d = fit_plane(points[inliers])
    residual = np.abs(points[inliers] @ normal + d)
    # Orient the normal to point UP (toward the camera, which is above the floor): in the
    # optical frame "up" is -y.
    if normal[1] > 0:
        normal, d = -normal, -d
    height = abs(d)   # the lens is at the origin: its distance to the plane

    # Optical -> camera_link (REP-103: x forward, y left, z up):
    # x_link = z_opt, y_link = -x_opt, z_link = -y_opt.
    up = np.array([normal[2], -normal[0], -normal[1]])
    pitch = math.atan2(-up[0], up[2])        # positive = camera pointing down
    roll = math.atan2(up[1], up[2])          # positive = left side up

    print(f'frames: {len(node.frames)}  floor points: {len(points)}  inliers: {int(inliers.sum())}  '
          f'residual: mean {residual.mean()*1000:.1f} mm, max {residual.max()*1000:.1f} mm')
    print(f'camera pitch: {math.degrees(pitch):.2f} deg down   roll: {math.degrees(roll):.2f} deg   '
          f'lens height above the floor: {height:.3f} m')
    print('for jetnano.urdf.xacro:')
    print(f'  camera_rpy = "{roll:.3f} {pitch:.3f} 0"')
    print(f'  camera_xyz z = {height - args.wheel_radius:.3f}   (height {height:.3f} - wheel_radius {args.wheel_radius})')
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
