# ROS 2 Humble prerequisites

The capture script delegates recording to the ROS 2 CLI. Install these ROS
packages in the ROS environment, not with the Python project installer:

```text
ros-humble-ros-base
ros-humble-ros2cli
ros-humble-rclpy
ros-humble-rosbag2
ros-humble-rosbag2-storage-mcap
ros-humble-sensor-msgs
ros-humble-tf2-msgs
```

The current script does not decode images or call `cv_bridge`; raw messages are
kept in the bag for later replay. If Humble's binary `rclpy` is not importable
under Python 3.13, use a clean source workspace outside this repository and
source only that workspace before running the experiment.

