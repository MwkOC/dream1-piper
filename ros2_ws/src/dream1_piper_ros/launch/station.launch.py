import os
import socket
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def _tcp_offset():
    configured = Path(os.getenv("RSTACK_ROBOT_CONFIG", "configs/app_robot.yaml")).expanduser()
    candidates = [configured] if configured.is_absolute() else [
        Path.cwd() / configured,
        Path.cwd().parent / configured,
        Path(__file__).resolve().parents[6] / configured,
    ]
    source = next((path.resolve() for path in candidates if path.is_file()), None)
    if source is None:
        raise RuntimeError(f"robot profile not found for ROS TCP calibration: {configured}")
    profile = yaml.safe_load(source.read_text(encoding="utf-8"))
    offset = profile["robot"]["options"]["tcp_offset"]
    if len(offset) != 6:
        raise ValueError("robot.options.tcp_offset must contain xyz/rpy values")
    return [float(value) for value in offset]


def _ensure_single_station_bridge():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", 8766))
        except OSError as exc:
            raise RuntimeError(
                "A Piper station bridge already owns 127.0.0.1:8766; "
                "stop the existing station.launch.py before starting another."
            ) from exc


def generate_launch_description():
    _ensure_single_station_bridge()
    package = get_package_share_directory("dream1_piper_ros")
    servo_config = str(Path(package) / "config/servo.yaml")
    description = Path(package) / "description"
    robot_description = (description / "piper.urdf").read_text(encoding="utf-8")
    robot_semantic = (description / "piper_bimanual.srdf").read_text(encoding="utf-8")
    tcp_offset = str(_tcp_offset())
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
                "follow": "true",
                # Keep MoveIt's simulated ros2_control state output away from
                # the physical driver's control/joint_states command input.
                "control_topic": "moveit_mock/joint_states",
                "use_rviz": "false",
                "speed_percent": os.getenv("RSTACK_ROBOT_SPEED_PERCENT", "20"),
                "tcp_offset": tcp_offset,
            }.items(),
        ))
        actions.append(Node(
            package="moveit_servo",
            executable="servo_node",
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
            "pose_metrics_hz": float(os.getenv("RSTACK_POSE_METRICS_HZ", "0.3333333333")),
            "pose_metrics_max_target_age_ms": float(
                os.getenv("RSTACK_POSE_METRICS_MAX_TARGET_AGE_MS", "250")
            ),
        }],
        output="screen",
    ))
    return LaunchDescription(actions)
