# Experiments

This folder contains the active Piper integration around Dream Labs' installed
packages. It does not contain the Dream Labs source tree or copy the Dream
station or policy client.

## Install

```bash
cd experiments
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip install -e '.[dream]'
# Only on the robot host:
python -m pip install -e '.[hardware]'
```

The `dream` extra installs the official `dreamlabs` distribution from PyPI.
No Dream Labs source tree is included in this repository or added through
`PYTHONPATH`.

## Piper driver and configuration

`piper/hardware_config.yaml` is the extracted `bi_piper` configuration from
`origin/temasA`. It declares `can0`/`can1`, calibration, camera roles, limits,
inference startup and URDF frames. `piper/active_driver.py` is the consolidated
CAN boundary: `PiperSdkArm` enables the arm after feedback seeding and
`PiperJointStreamer` applies velocity and acceleration limits.

`piper/robot.py` exposes `Piper` and `BiPiper`, including transactional
connection, safe disconnect, home/reset handling and telemetry snapshots.
Instantiating these classes can enable motors and send commands; use them only
on the robot host with supervision.

The local robot ID is `bi_piper`. It is not a Dream Labs embodiment ID. The
Dream probe keeps `other_embodiment` until a real remote embodiment is supplied.

To inspect accessible Dream models without hardware:

```bash
cd experiments
set -a; . .env; set +a
dream-piper-models --models
```

To inspect one Dream action chunk without moving motors:

```bash
dream-piper-models --infer --prompt 'pick up the soft object'
```

`--execute` is an explicit hardware action. It validates the complete EEF
chunk through IK before enabling either arm:

```bash
dream-piper-models --infer --execute --prompt 'pick up the soft object'
```

## Raw ROS capture

```bash
python -m capture.record_episode \
  --config experiments/capture/topics.yaml \
  --output experiments/data/episode-0001 \
  --task 'pick up the soft object' \
  --duration 30 \
  --dry-run
```

Without `--dry-run`, the script delegates recording to `ros2 bag record` and
writes a raw bag plus `manifest.json`. It never sends robot commands.

