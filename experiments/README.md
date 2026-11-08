# Experiments

This folder contains the project-specific integration around Dream Labs'
installed packages. It does not contain the Dream Labs source tree or copy the
Dream station, policy client, pacing, IK, or action loop.

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
`origin/temasA` (`e67a701`, `9426238`). It declares `can0`/`can1`, calibration,
camera roles, limits and URDF frames. `piper/active_driver.py` is the local
Piper CAN boundary; constructing `PiperSdkArm` enables the arm and can send
commands. The separate `piper/piper_driver.py` remains the feedback-only
adapter for Dream's custom-driver contract.

The local robot ID is `bi_piper`. It is not a Dream Labs embodiment ID. The
Dream probe keeps `other_embodiment` until a real remote embodiment is supplied.

To inspect accessible Dream models without hardware:

```bash
cd experiments
set -a; . .env; set +a
dream-piper-models --models
```

For the feedback-only official station template, retain `--dry-run` until the
TCP, calibration and hardware procedure are confirmed:

```bash
dreamcli robot run \
  --config experiments/piper/station.readonly.yaml \
  --checkpoint '<REAL_CHECKPOINT>' \
  --task 'pick up the soft object' \
  --dry-run
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

