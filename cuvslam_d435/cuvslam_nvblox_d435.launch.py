"""cuVSLAM odometry plus nvblox 3D mapping from one D435, projector alternating.

cuVSLAM wants the infrared pair with the projector OFF (its dot pattern moves with
the camera and would be tracked as if it were the world); nvblox wants depth with
the projector ON. NVIDIA's answer, copied here from nvblox_examples_bringup
(release-4.6): the camera flashes the emitter on alternate frames
(depth_module.emitter_on_off) and a splitter node reads each frame's metadata and
routes projector-off frames to the infrared outputs and projector-on frames to the
depth output. Each consumer therefore sees half the camera's frame rate.

Everything runs in one component container inside the isaac_vo container:

    ros2 launch /workspaces/isaac_ros-dev/cuvslam_nvblox_d435.launch.py
    ros2 launch ... profile:=640,480,60 base_frame:=base_link

cuVSLAM is odometry only and publishes /vo (no TF): the host EKF keeps owning
odom -> base_footprint. nvblox builds its map in the odom frame from TF and
publishes /nvblox_node/static_map_slice (a nvblox_msgs/DistanceMapSlice for the
Nav2 costmap plugin), /nvblox_node/static_esdf_pointcloud and /nvblox_node/mesh.
The host's realsense2_camera node must be stopped first (one camera owner).

The colour stream is on as well, for people rather than nodes: the camera
publishes it JPEG-compressed (/camera/color/image_raw/compressed, for RViz over
Wi-Fi) and a web_video_server in the same container serves it to any browser on
port 8080. Nothing on the robot subscribes to either, and image_transport only
encodes for subscribers, so they cost nothing until someone looks. They live in
this container because the compressed transport and web_video_server debs cannot
go on the Jetson host: apt would replace JetPack's OpenCV and remove
nvidia-jetpack to install them (checked 2026-09-23).
"""

import os

import launch
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterValue

# NVIDIA's nvblox_base.yaml (release-4.6), copied into the workspace: the package it
# ships in (nvblox_examples_bringup) drags the people-segmentation DNN stack into the
# container, which the robot does not need.
NVBLOX_BASE = '/workspaces/isaac_ros-dev/nvblox_base.yaml'


def generate_launch_description():
    profile = LaunchConfiguration('profile')
    base_frame = LaunchConfiguration('base_frame')
    jitter_ms = LaunchConfiguration('image_jitter_threshold_ms')
    ground = LaunchConfiguration('ground_constraint')
    voxel = LaunchConfiguration('voxel_size')
    slice_min = LaunchConfiguration('slice_min_height')
    slice_max = LaunchConfiguration('slice_max_height')
    color = LaunchConfiguration('color')
    color_profile = LaunchConfiguration('color_profile')
    web_video = LaunchConfiguration('web_video')
    web_video_port = LaunchConfiguration('web_video_port')

    # The camera: IR pair + depth from the depth module, projector flashing,
    # plus the colour sensor for the video feed. No alignment, no sync: the
    # splitter pairs frames by their own metadata, and nothing pairs colour.
    realsense_camera_node = Node(
        name='camera',
        namespace='',
        package='realsense2_camera',
        executable='realsense2_camera_node',
        output='screen',
        # If either process dies, take the whole launch down: the wrapper on the
        # host then exits and its launch respawns everything cleanly.
        on_exit=[Shutdown(reason='realsense2_camera_node exited')],
        parameters=[{
            'enable_infra1': True,
            'enable_infra2': True,
            'enable_depth': True,
            'enable_color': ParameterValue(color, value_type=bool),
            'enable_gyro': False,
            'enable_accel': False,
            'depth_module.emitter_enabled': 1,
            'depth_module.emitter_on_off': True,
            'depth_module.infra_profile': profile,
            'depth_module.depth_profile': profile,
            'depth_module.profile': profile,
            'rgb_camera.color_profile': color_profile,
            'rgb_camera.profile': color_profile,
            'align_depth.enable': False,
            'enable_sync': False,
            'pointcloud.enable': False,
            'depth_qos': 'SENSOR_DATA',
            'depth_info_qos': 'SENSOR_DATA',
            'infra_qos': 'SENSOR_DATA',
            # Colour stays reliable, unlike the streams above: RViz's Image
            # display and web_video_server subscribe reliably by default, and a
            # best-effort publisher never matches a reliable subscriber.
            'color_qos': 'DEFAULT',
            'color_info_qos': 'DEFAULT',
            'initial_reset': True,
        }],
    )

    # Routes projector-off frames to infra outputs, projector-on frames to depth.
    splitter_node = ComposableNode(
        namespace='camera',
        name='realsense_splitter_node',
        package='realsense_splitter',
        plugin='nvblox::RealsenseSplitterNode',
        parameters=[{'input_qos': 'SENSOR_DATA', 'output_qos': 'SENSOR_DATA'}],
        remappings=[
            ('input/infra_1', '/camera/infra1/image_rect_raw'),
            ('input/infra_1_metadata', '/camera/infra1/metadata'),
            ('input/infra_2', '/camera/infra2/image_rect_raw'),
            ('input/infra_2_metadata', '/camera/infra2/metadata'),
            ('input/depth', '/camera/depth/image_rect_raw'),
            ('input/depth_metadata', '/camera/depth/metadata'),
            ('input/pointcloud', '/camera/depth/color/points'),
            ('input/pointcloud_metadata', '/camera/depth/metadata'),
        ],
    )

    visual_slam_node = ComposableNode(
        name='visual_slam_node',
        package='isaac_ros_visual_slam',
        plugin='nvidia::isaac_ros::visual_slam::VisualSlamNode',
        parameters=[{
            'num_cameras': 2,
            'tracking_mode': 0,                        # stereo, no IMU
            'rectified_images': True,
            'enable_image_denoising': False,
            'image_jitter_threshold_ms': ParameterValue(jitter_ms, value_type=float),
            'enable_localization_n_mapping': False,    # odometry only
            'publish_odom_to_base_tf': False,          # the EKF owns odom -> base_footprint
            'publish_map_to_odom_tf': False,
            'enable_ground_constraint_in_odometry': ParameterValue(ground, value_type=bool),
            'enable_slam_visualization': False,
            'enable_landmarks_view': False,
            'enable_observations_view': False,
            'base_frame': base_frame,
            'odom_frame': 'odom',
            'camera_optical_frames': [
                'camera_infra1_optical_frame',
                'camera_infra2_optical_frame',
            ],
        }],
        remappings=[
            ('visual_slam/image_0', '/camera/realsense_splitter_node/output/infra_1'),
            ('visual_slam/camera_info_0', '/camera/infra1/camera_info'),
            ('visual_slam/image_1', '/camera/realsense_splitter_node/output/infra_2'),
            ('visual_slam/camera_info_1', '/camera/infra2/camera_info'),
            ('visual_slam/tracking/odometry', '/vo'),
        ],
    )

    # NVIDIA's base parameters, then what is specific to this robot: the map is
    # built in odom from TF (odom -> base_footprint -> base_link -> camera), the
    # 2D slice for Nav2 spans from just below the floor (odom z = 0 is the floor,
    # where base_footprint started) to the top of the chassis, and the colour
    # stream is not used for the map (it exists for the video feed only).
    nvblox_node = ComposableNode(
        name='nvblox_node',
        package='nvblox_ros',
        plugin='nvblox::NvbloxNode',
        parameters=[NVBLOX_BASE, {
            'num_cameras': 1,
            'use_depth': True,
            'use_color': False,
            'use_lidar': False,
            'global_frame': 'odom',
            'pose_frame': base_frame,
            'use_tf_transforms': True,
            'map_clearing_frame_id': base_frame,
            'esdf_slice_bounds_visualization_attachment_frame_id': base_frame,
            'workspace_height_bounds_visualization_attachment_frame_id': base_frame,
            'voxel_size': ParameterValue(voxel, value_type=float),
            'esdf_mode': '2d',
            'mapping_type': 'static_tsdf',
            'input_qos': 'SENSOR_DATA',
            'static_mapper.esdf_slice_height': 0.0,
            'static_mapper.esdf_slice_min_height': ParameterValue(slice_min, value_type=float),
            'static_mapper.esdf_slice_max_height': ParameterValue(slice_max, value_type=float),
        }],
        remappings=[
            ('camera_0/depth/image', '/camera/realsense_splitter_node/output/depth'),
            ('camera_0/depth/camera_info', '/camera/depth/camera_info'),
        ],
    )

    container = ComposableNodeContainer(
        name='nvblox_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container_mt',
        composable_node_descriptions=[splitter_node, visual_slam_node, nvblox_node],
        output='screen',
        on_exit=[Shutdown(reason='nvblox container exited')],
    )

    # The browser feed. ros_compressed passes the camera's own JPEG frames
    # through as MJPEG, so this encodes nothing; it subscribes only while a
    # browser is connected. Not fatal to the launch: odometry does not need it.
    #     http://<robot>:8080/                                        topic list
    #     http://<robot>:8080/stream?topic=/camera/color/image_raw    the feed
    web_video_node = Node(
        package='web_video_server',
        executable='web_video_server',
        name='web_video_server',
        output='screen',
        condition=IfCondition(web_video),
        respawn=True,
        respawn_delay=5.0,
        parameters=[{
            'port': ParameterValue(web_video_port, value_type=int),
            'address': '0.0.0.0',
            'default_stream_type': 'ros_compressed',
            'verbose': False,
        }],
    )

    return launch.LaunchDescription([
        DeclareLaunchArgument('profile', default_value='640,360,90',
                              description="depth-module profile 'W,H,FPS' shared by IR and depth; each consumer gets half the FPS"),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument('image_jitter_threshold_ms', default_value='100.0',
                              description='cuVSLAM logs a warning for a gap between stereo pairs above this (the pair is still used); '
                                          'pairs arrive every 22 ms nominal with the emitter alternating, and the camera drops some'),
        DeclareLaunchArgument('ground_constraint', default_value='false'),
        DeclareLaunchArgument('voxel_size', default_value='0.05'),
        DeclareLaunchArgument('slice_min_height', default_value='0.10',
                              description='nvblox 2D slice: lowest obstacle height, odom frame (floor = 0; any lower and the floor itself is marked)'),
        DeclareLaunchArgument('slice_max_height', default_value='0.35',
                              description='nvblox 2D slice: highest obstacle height, odom frame (chassis top)'),
        DeclareLaunchArgument('color', default_value='true',
                              description='stream the colour camera too, for RViz and the browser feed; nothing on the robot uses it'),
        DeclareLaunchArgument('color_profile', default_value='640,480,30',
                              description="colour stream 'W,H,FPS'"),
        DeclareLaunchArgument('web_video', default_value='true',
                              description='serve the compressed colour stream over HTTP (web_video_server)'),
        DeclareLaunchArgument('web_video_port', default_value='8080'),
        container,
        realsense_camera_node,
        web_video_node,
    ])
