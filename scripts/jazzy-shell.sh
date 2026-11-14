#!/usr/bin/env bash
# Keep ROS's system Python separate from Dream's Python 3.13 environment.
set -euo pipefail
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo 'ROS Jazzy is not installed. Install Ubuntu 24.04 and Jazzy first.' >&2
  exit 1
fi
if ! /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
  echo 'This launcher requires Ubuntu system Python 3.12.' >&2
  exit 1
fi
exec env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV -u CONDA_PREFIX \
  -u CONDA_DEFAULT_ENV -u LD_LIBRARY_PATH -u AMENT_PREFIX_PATH \
  -u CMAKE_PREFIX_PATH -u COLCON_PREFIX_PATH -u ROS_DISTRO \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PYTHONNOUSERSITE=1 bash --noprofile --norc -c '
    source /opt/ros/jazzy/setup.bash
    if (( $# )); then
      exec "$@"
    fi
    exec bash --noprofile --norc -i
  ' jazzy-shell "$@"
