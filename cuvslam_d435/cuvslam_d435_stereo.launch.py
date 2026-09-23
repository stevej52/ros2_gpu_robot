"""cuVSLAM stereo odometry from the D435's infrared pair, as a drop-in for rtabmap rgbd_odometry.

Derived from NVIDIA's isaac_ros_visual_slam_realsense.launch.py (release-4.6) with the IMU parts
removed (the D435 has no IMU; the BNO055 is fused downstream by robot_localization) and the
node run as pure odometry: no SLAM, no map->odom, no odom->base TF. It publishes nav_msgs/Odometry
on /vo, exactly where rgbd_odometry used to, so ekf.yaml is unchanged and the EKF keeps owning
odom -> base_footprint.

    ros2 launch /workspaces/isaac_ros-dev/cuvslam_d435_stereo.launch.py
    ros2 launch ... infra_profile:=848,480,60 base_frame:=camera_link

The host's realsense2_camera node must be stopped first: the camera can have one owner.
"""

import launch
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    infra_profile = LaunchConfiguration('infra_profile')
    base_frame = LaunchConfiguration('base_frame')
    jitter_ms = LaunchConfiguration('image_jitter_threshold_ms')
    ground = LaunchConfiguration('ground_constraint')
    emitter = LaunchConfiguration('emitter')

    realsense_camera_node = Node(
        name='camera',
        namespace='',
        package='realsense2_camera',
        executable='realsense2_camera_node',
        output='screen',
        parameters=[{
            'enable_infra1': True,
            'enable_infra2': True,
            'enable_color': False,
            'enable_depth': False,
            'enable_gyro': False,
            'enable_accel': False,
            # Projector off: its dot pattern moves with the camera and would be tracked as
            # if it were the world. Stereo on ambient light only.
            'depth_module.emitter_enabled': ParameterValue(emitter, value_type=int),
            'depth_module.infra_profile': infra_profile,
            'depth_module.profile': infra_profile,
            'initial_reset': True,
        }],
    )

    visual_slam_node = ComposableNode(
        name='visual_slam_node',
        package='isaac_ros_visual_slam',
        plugin='nvidia::isaac_ros::visual_slam::VisualSlamNode',
        parameters=[{
            'num_cameras': 2,
            'tracking_mode': 0,                 # stereo, no IMU
            'rectified_images': True,           # infraN/image_rect_raw is rectified on-camera
            'enable_image_denoising': False,
            'image_jitter_threshold_ms': ParameterValue(jitter_ms, value_type=float),
            'enable_localization_n_mapping': False,   # odometry only
            'publish_odom_to_base_tf': False,         # the EKF owns odom -> base_footprint
            'publish_map_to_odom_tf': False,          # slam_toolbox owns map -> odom
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
            ('visual_slam/image_0', 'camera/infra1/image_rect_raw'),
            ('visual_slam/camera_info_0', 'camera/infra1/camera_info'),
            ('visual_slam/image_1', 'camera/infra2/image_rect_raw'),
            ('visual_slam/camera_info_1', 'camera/infra2/camera_info'),
            ('visual_slam/tracking/odometry', '/vo'),
        ],
    )

    container = ComposableNodeContainer(
        name='visual_slam_launch_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[visual_slam_node],
        output='screen',
    )

    return launch.LaunchDescription([
        DeclareLaunchArgument('infra_profile', default_value='640,360,60',
                              description="IR stream profile 'W,H,FPS'; the D435 offers 640x360 and 848x480 at up to 90"),
        DeclareLaunchArgument('base_frame', default_value='base_link',
                              description='frame the odometry is expressed for; needs TF base_frame -> camera optical frames'),
        DeclareLaunchArgument('image_jitter_threshold_ms', default_value='19.0',
                              description='max gap between consecutive stereo pairs; 19 for 60 fps, 34 for 30 fps'),
        DeclareLaunchArgument('emitter', default_value='0',
                              description='IR projector: 0 off (real tracking), 1 on (dot pattern - static-bench load test only)'),
        DeclareLaunchArgument('ground_constraint', default_value='false',
                              description='constrain odometry to a horizontal plane (not for rocks)'),
        container,
        realsense_camera_node,
    ])
