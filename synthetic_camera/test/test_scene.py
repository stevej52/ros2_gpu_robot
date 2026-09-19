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

"""The scene maths, which needs numpy but not ROS."""

import numpy as np
import pytest

from synthetic_camera.scene import CameraModel, CorridorScene, build_ring, make_texture


def test_camera_matrices_have_the_shapes_ros_expects():
    camera = CameraModel()
    assert len(camera.k_matrix()) == 9
    assert len(camera.p_matrix()) == 12
    assert camera.k_matrix()[2] == pytest.approx(camera.cx)
    assert camera.p_matrix()[3] == 0.0


def test_texture_is_deterministic_and_high_contrast():
    first = make_texture(size=256, seed=7)
    second = make_texture(size=256, seed=7)
    assert np.array_equal(first, second), 'same seed must give the same texture'
    # A flat texture would give the odometry nothing to track, which would make
    # the whole benchmark meaningless. Guard the property, not the pixels.
    assert first.std() > 30.0


def test_colour_frame_shape_and_type():
    scene = CorridorScene(camera=CameraModel(width=64, height=48))
    frame = scene.colour(0)
    assert frame.shape == (48, 64, 3)
    assert frame.dtype == np.uint8


def test_scene_actually_moves():
    scene = CorridorScene(camera=CameraModel(width=64, height=48))
    assert not np.array_equal(scene.colour(0), scene.colour(25)), \
        'frames must differ or there is no motion to estimate'


def test_depth_is_millimetres_within_the_configured_range():
    scene = CorridorScene(camera=CameraModel(width=64, height=48),
                          z_near=0.6, z_far=4.0)
    depth = scene.depth_u16()
    assert depth.dtype == np.uint16
    assert depth.min() >= 600 and depth.max() <= 4000


def test_depth_recedes_up_the_image():
    """The floor at the bottom must be nearer than the wall at the top."""
    scene = CorridorScene(camera=CameraModel(width=64, height=48))
    depth = scene.depth_u16()
    assert depth[-1, :].mean() < depth[0, :].mean()


def test_ring_buffer_sizes_match_the_encodings():
    camera = CameraModel(width=64, height=48)
    scene = CorridorScene(camera=camera)
    colours, depth = build_ring(scene, frames=4)
    assert len(colours) == 4
    assert len(colours[0]) == 64 * 48 * 3, 'rgb8 is three bytes a pixel'
    assert len(depth) == 64 * 48 * 2, '16UC1 is two bytes a pixel'
