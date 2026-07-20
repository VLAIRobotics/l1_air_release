#!/usr/bin/env python3
# Copyright 2026 vlai
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
单个相机启动文件（用于测试）
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, TextSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'camera_name',
            default_value='camera',
            description='相机名称'
        ),

        DeclareLaunchArgument(
            'serial_no',
            default_value=TextSubstitution(text=''),
            description='相机序列号（字符串）'
        ),

        DeclareLaunchArgument(
            'color_width',
            default_value='640',
            description='RGB 图像宽度'
        ),

        DeclareLaunchArgument(
            'color_height',
            default_value='480',
            description='RGB 图像高度'
        ),

        DeclareLaunchArgument(
            'fps',
            default_value='30',
            description='帧率'
        ),

        Node(
            package='realsense2_camera',
            executable='realsense2_camera_node',
            name=LaunchConfiguration('camera_name'),
            namespace=LaunchConfiguration('camera_name'),
            parameters=[{
                'serial_no': LaunchConfiguration('serial_no'),  # 作为字符串
                'device_type': 'd435',
                'enable_color': True,
                'enable_depth': True,
                'align_depth.enable': True,
                'rgb_camera.profile': '640x480x30',
                'depth_module.profile': '640x480x30',
                'enable_gyro': False,
                'enable_accel': False,
                'enable_infra1': False,
                'enable_infra2': False,
                'publish_tf': True,
                'tf_publish_rate': 0.0,
            }],
            output='screen',
            emulate_tty=True,
        )
    ])