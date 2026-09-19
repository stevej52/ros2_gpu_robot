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
Synthetic RGB-D frames of a textured corridor, for benchmarking.

The point of this module is to give visual odometry something real to do
without a camera plugged in. A plain gradient or a solid colour would be
useless: ``rgbd_odometry`` would find no corners, track nothing, and the
benchmark would measure the failure path instead of the work path. So the
scene is deliberately textured, and it moves with a correct pinhole
projection so that features shift the way they would on a real robot.

The model is a corridor: a back wall at ``z_far`` that the camera drives
towards, and a floor that recedes from ``z_near`` at the bottom of the image
up to the wall. A point at depth ``z`` projects with scale ``f / z``, so as
the camera advances the wall texture magnifies and the floor slides past.
That gives both the feature motion and the depth structure an RGB-D odometry
node needs to estimate translation.

Nothing here imports ROS, so the frame maths can be tested with plain pytest
and the cost of generating a frame can be measured on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CameraModel:
    """Pinhole intrinsics. Defaults approximate a D435 colour stream at 640x480."""

    width: int = 640
    height: int = 480
    fx: float = 615.0
    fy: float = 615.0

    @property
    def cx(self) -> float:
        """Principal point x, taken at the image centre."""
        return (self.width - 1) / 2.0

    @property
    def cy(self) -> float:
        """Principal point y, taken at the image centre."""
        return (self.height - 1) / 2.0

    def k_matrix(self) -> list[float]:
        """Return K in the row-major order sensor_msgs/CameraInfo expects."""
        return [self.fx, 0.0, self.cx,
                0.0, self.fy, self.cy,
                0.0, 0.0, 1.0]

    def p_matrix(self) -> list[float]:
        """Return P for a monocular camera: K with a zero fourth column."""
        return [self.fx, 0.0, self.cx, 0.0,
                0.0, self.fy, self.cy, 0.0,
                0.0, 0.0, 1.0, 0.0]


def make_texture(size: int = 1024, seed: int = 20260919, blocks: int = 64) -> np.ndarray:
    """
    Build one deterministic, corner-rich texture to map onto the scene.

    Random blocks give strong corners at every block boundary, which is what
    corner detectors key on; the per-pixel noise on top stops large flat
    regions from being ambiguous to a descriptor. The same ``seed`` always
    gives the same texture, so two benchmark runs are comparable.
    """
    rng = np.random.default_rng(seed)
    coarse = rng.integers(40, 216, size=(blocks, blocks, 3), dtype=np.uint8)
    repeat = max(1, size // blocks)
    texture = np.repeat(np.repeat(coarse, repeat, axis=0), repeat, axis=1)
    texture = texture[:size, :size]
    noise = rng.integers(-12, 13, size=texture.shape, dtype=np.int16)
    return np.clip(texture.astype(np.int16) + noise, 0, 255).astype(np.uint8)


@dataclass
class CorridorScene:
    """
    A textured corridor the camera drives down, rendered frame by frame.

    ``z_near``/``z_far`` bracket the depths present in the image, ``speed`` is
    the forward travel per frame in metres, and ``horizon`` is the fraction of
    the image height taken by the wall (the rest is floor).
    """

    camera: CameraModel = CameraModel()
    z_near: float = 0.6
    z_far: float = 4.0
    speed: float = 0.02
    horizon: float = 0.55
    seed: int = 20260919

    def __post_init__(self) -> None:
        """Precompute the texture and the per-pixel depth, which never change."""
        self._texture = make_texture(seed=self.seed)
        self._depth_m = self._depth_metres()

    def _depth_metres(self) -> np.ndarray:
        """Depth of every pixel: constant on the wall, receding on the floor."""
        height, width = self.camera.height, self.camera.width
        split = int(height * self.horizon)
        depth = np.empty((height, width), dtype=np.float32)
        depth[:split, :] = self.z_far
        floor_rows = height - split
        if floor_rows > 0:
            # Bottom of the image is closest; it reaches the wall at the split.
            ramp = np.linspace(self.z_far, self.z_near, floor_rows, dtype=np.float32)
            depth[split:, :] = ramp[:, None]
        return depth

    def depth_u16(self) -> np.ndarray:
        """Depth as millimetres in uint16, the encoding RealSense publishes."""
        return (self._depth_m * 1000.0).astype(np.uint16)

    def colour(self, frame: int) -> np.ndarray:
        """
        Render the corridor for one frame index, as HxWx3 uint8 RGB.

        Each pixel samples the texture at a position scaled by ``f / z``, so
        near pixels (the floor at the bottom) sweep past quickly and far ones
        (the wall) creep. That difference is the parallax the odometry solves.
        """
        camera = self.camera
        travelled = self.speed * frame
        # Depth in front of the camera after travelling; clamp so it never
        # reaches zero and blows the scale up.
        z = np.maximum(self._depth_m - travelled, 0.25)
        scale = camera.fx / z

        ys = np.arange(camera.height, dtype=np.float32)[:, None] - camera.cy
        xs = np.arange(camera.width, dtype=np.float32)[None, :] - camera.cx
        size = self._texture.shape[0]
        # World coordinates of each ray at its depth, then back to texel space.
        u = (xs / scale * 200.0) % size
        v = (ys / scale * 200.0 + travelled * 120.0) % size
        return self._texture[v.astype(np.intp), u.astype(np.intp)]


def playback_order(frames: int) -> list[int]:
    """
    Return the frame indices to publish in a loop, forward then backward.

    A ring that jumps from the last frame straight back to the first is a
    teleport to the odometry: it loses tracking there, once per loop, and the
    recovery shows up in its logs as if the camera had failed. Playing the
    frames forward and then backward keeps position continuous; only the
    velocity reverses, which an odometry node takes in its stride.
    """
    if frames <= 2:
        return list(range(frames))
    return list(range(frames)) + list(range(frames - 2, 0, -1))


def build_ring(scene: CorridorScene, frames: int) -> tuple[list[bytes], bytes]:
    """
    Pre-render ``frames`` colour frames once, plus the single depth frame.

    Publishing precomputed bytes keeps the publisher's own cost near zero, so
    a measurement of the odometry node is not polluted by the cost of making
    its input. Depth is constant in this scene, so one buffer serves them all.
    """
    colours = [scene.colour(index).tobytes() for index in range(frames)]
    return colours, scene.depth_u16().tobytes()
