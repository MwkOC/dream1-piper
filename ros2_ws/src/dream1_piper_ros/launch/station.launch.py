import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    package = get_package_share_directory("dream1_piper_ros")
    servo_config = str(Path(package) / "config/servo.yaml")
    description = Path(package) / "description"
    robot_description = (description / "piper.urdf").read_text(encoding="utf-8")
    robot_semantic = (description / "piper_bimanual.srdf").read_text(encoding="utf-8")
    driver_launch = Path(get_package_share_directory("agx_arm_ctrl")) / "launch/start_single_agx_arm_moveit.launch.py"
    actions = []
    for side, env_key, tcp in (("left", "RSTACK_CAN_LEFT", "left_tcp"), ("right", "RSTACK_CAN_RIGHT", "right_tcp")):
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(driver_launch)),
            launch_arguments={
                "namespace": side,
                "can_port": os.getenv(env_key, "can0" if side == "left" else "can1"),
                "arm_type": "piper",
                "effector_type": "agx_gripper",
                "auto_enable": "false",
                "auto_control_gate": "true",
                "control_gate_service": f"/{side}/control_enable",
                "use_rviz": "false",
                "speed_percent": os.getenv("RSTACK_ROBOT_SPEED_PERCENT", "20"),
            }.items(),
        ))
        actions.append(Node(
            package="moveit_servo",
            executable="servo_node_main",
            namespace=side,
            name="servo_node",
            parameters=[servo_config, {"robot_description": robot_description, "robot_description_semantic": robot_semantic, "moveit_servo": {
                "move_group_name": f"{side}_arm",
                "planning_frame": "world",
                "ee_frame_name": tcp,
                "robot_link_command_frame": f"{side}_base_link",
                "cartesian_command_in_topic": "~/delta_twist_cmds",
                "command_out_topic": "~/command",
            }}],
            output="screen",
        ))
    actions.append(Node(
        package="dream1_piper_ros",
        executable="station_bridge",
        parameters=[{
            "home_duration_s": float(os.getenv("RSTACK_HOME_DURATION_S", "3.0")),
            "home_tolerance_rad": float(os.getenv("RSTACK_HOME_TOLERANCE_RAD", "0.08")),
        }],
        output="screen",
    ))
    return LaunchDescription(actions)
