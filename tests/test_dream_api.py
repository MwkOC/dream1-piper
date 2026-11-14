"""Offline Dream/Piper contract tests; direct execution runs the connection CLI."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.constants import PIPER_JOINT_LOWER_RAD, PIPER_JOINT_UPPER_RAD
from scripts.dreamlabs import main, make_observation, solve_chunk
from scripts.driver import PiperGripperRange, PiperJointStreamer, PiperSdkArm
from scripts.kinematics import PiperKinematics


def solvers():
    return {side: PiperKinematics(ROOT / 'assets/piper/piper.urdf',
                                 f'{side}_base_link', f'{side}_tcp', side)
            for side in ('left', 'right')}


def test_camera_jpegs_have_model_size_and_centered_wrist_crop():
    import base64
    import cv2
    from scripts.dreamlabs import Cameras

    # Red borders must disappear from a 4:3 wrist; blue center stays BGR.
    wrist = np.zeros((384, 512, 3), dtype=np.uint8)
    wrist[:] = (0, 0, 255)
    wrist[48:336] = (255, 0, 0)
    class Device:
        def read(self):
            return True, wrist.copy()

    cameras = object.__new__(Cameras)
    cameras.wrist_maps = {}
    cameras.devices = {
        'overhead': ('zedmini', type('Zed', (), {
            'read': lambda self: np.zeros((376, 672, 3), dtype=np.uint8)})()),
        'wrist_l': ('opencv', Device()),
        'wrist_r': ('opencv', Device()),
    }
    frames = cameras.frames()
    assert set(frames) == {'video.overhead', 'video.wrist_l', 'video.wrist_r'}
    for key, encoded in frames.items():
        decoded = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), np.uint8),
                               cv2.IMREAD_COLOR)
        assert decoded.shape == (176, 320, 3)
        if key != 'video.overhead':
            assert decoded[:, :, 0].min() > 240
            assert decoded[:, :, 2].max() < 10


def test_observation_and_eef_chunk_roundtrip():
    models = solvers()
    q = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    states = {side: (q, 0.4) for side in models}
    obs = make_observation(states, models, 'test task')
    parts = {}
    for side in models:
        assert obs[f'state.{side}_arm'] == [0.] * 6
        for part in ('eef_xyz', 'eef_rot6', 'grip'):
            parts[f'action.{side}_{part}'] = [obs[f'state.{side}_{part}']] * 2
    actions = solve_chunk({'per_key': parts}, models, {side: q + 0.01 for side in models})
    assert len(actions) == 2
    for action in actions:
        for side, model in models.items():
            target = np.array([action[f'{side}_joint{i}'] for i in range(1, 7)])
            np.testing.assert_allclose(model.forward_matrix(target), model.forward_matrix(q), atol=1e-4)
            assert action[f'{side}_gripper'] == 0.4


@pytest.mark.parametrize('bad', [np.full(6, np.nan), PIPER_JOINT_UPPER_RAD + .01,
                                  PIPER_JOINT_LOWER_RAD - .01])
def test_driver_rejects_invalid_targets_before_can(bad):
    arm = object.__new__(PiperSdkArm)
    # No CAN interface: validation must fail before accessing one.
    with pytest.raises(ValueError):
        arm.send_joints_rad(bad)
    streamer = object.__new__(PiperJointStreamer)
    with pytest.raises(ValueError):
        streamer.set_target(bad)


def test_driver_units_and_gripper():
    class Can:
        def JointCtrl(self, *values):
            self.values = values
    arm = object.__new__(PiperSdkArm)
    arm.arm = Can()
    q = np.array([np.pi / 2, np.pi / 2, -np.pi / 2, 0, 0, 0])
    arm.send_joints_rad(q)
    assert arm.arm.values == (90000, 90000, -90000, 0, 0, 0)
    grip = PiperGripperRange(200, 70200)
    assert grip.command_for_opening(.5) == 35200
    assert grip.normalize(35200) == .5


def test_late_unreachable_row_prevents_whole_chunk():
    models = solvers()
    q = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    obs = make_observation({s: (q, .4) for s in models}, models, 'test')
    parts = {f'action.{s}_{part}': [obs[f'state.{s}_{part}']] * 2
             for s in models for part in ('eef_xyz', 'eef_rot6', 'grip')}
    parts['action.right_eef_xyz'][1] = [10., 10., 10.]
    with pytest.raises(ValueError, match='could not reach'):
        solve_chunk({'per_key': parts}, models, {s: q for s in models})


@pytest.mark.parametrize('corruption', ['missing', 'nan', 'length', 'gripper', 'rotation'])
def test_reject_malformed_reply(corruption):
    models = solvers()
    q = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    obs = make_observation({s: (q, .4) for s in models}, models, 'test')
    parts = {f'action.{s}_{p}': [obs[f'state.{s}_{p}']] for s in models
             for p in ('eef_xyz', 'eef_rot6', 'grip')}
    if corruption == 'missing':
        del parts['action.right_eef_xyz']
    elif corruption == 'nan':
        parts['action.right_eef_rot6'] = [[np.nan] * 6]
    elif corruption == 'length':
        parts['action.right_eef_xyz'] *= 2
    elif corruption == 'gripper':
        parts['action.right_grip'] = [1.2]
    else:
        parts['action.right_eef_rot6'] = [[0.] * 6]
    with pytest.raises(ValueError):
        solve_chunk({'per_key': parts}, models, {s: q for s in models})


@pytest.mark.parametrize('execute', [False, True])
def test_complete_cli_flow_with_simulated_hardware(monkeypatch, execute):
    import argparse
    import types
    import dream
    import scripts.dreamlabs as connection
    import scripts.piper as piper

    models = solvers()
    q = (PIPER_JOINT_LOWER_RAD + PIPER_JOINT_UPPER_RAD) / 2
    calls = {'sent': [], 'feedback_closed': 0, 'stopped': 0}

    class Feedback:
        def __init__(self, *args):
            pass
        def read(self):
            return q.copy(), .4
        def disconnect(self):
            calls['feedback_closed'] += 1

    class Robot:
        def __init__(self, config):
            calls['robot_created'] = True
            assert config.max_joint_speed_deg_s == 30.
            assert config.max_joint_acceleration_deg_s2 == 120.
            assert config.speed_percent == 20
            for side in ('left', 'right'):
                setattr(self, side, types.SimpleNamespace(
                    read_joints_rad=lambda: q.copy(),
                    _arm=types.SimpleNamespace(read_gripper_opening=lambda: .4)))
        def connect(self):
            calls['connected'] = True
        def move_to_initial_pose(self):
            assert calls['connected']
            calls['initial_pose_reached'] = True
        def disconnect(self):
            calls['disconnected'] = True
        def stop_motion(self):
            calls['stopped'] += 1
        def send_action(self, action):
            calls['sent'].append(action)

    class Camera:
        def __init__(self, *args):
            pass
        def frames(self):
            return {f'video.{r}': 'jpeg-base64' for r in ('overhead', 'wrist_l', 'wrist_r')}

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls['client_closed'] = True
        def policy(self, config):
            assert config['robot'] == 'other_embodiment'
            assert 'ik' not in config
        def set_observation(self, frames, obs, timestamp):
            if execute:
                assert calls['initial_pose_reached']
            self.obs = obs
            assert set(frames) == {'video.overhead', 'video.wrist_l', 'video.wrist_r'}
        def get_action(self):
            return {'per_key': {f'action.{s}_{p}': [self.obs[f'state.{s}_{p}']]
                                for s in models for p in ('eef_xyz', 'eef_rot6', 'grip')}}

    # Advance a local clock to test timing without sleeping or touching hardware.
    clock = [0.]
    def monotonic():
        clock[0] += .001
        return clock[0]
    monkeypatch.setattr(connection, 'time', types.SimpleNamespace(
        monotonic=monotonic, sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)))
    monkeypatch.setattr(connection, 'Cameras', Camera)
    monkeypatch.setattr(connection, 'PiperFeedbackArm', Feedback)
    monkeypatch.setattr(connection, 'load_piper_gripper_calibrations',
                        lambda path: {s: PiperGripperRange(0, 70000) for s in models})
    monkeypatch.setattr(piper, 'BiPiper', Robot)
    monkeypatch.setattr(dream, 'DreamClient', Client)
    connection.run(argparse.Namespace(
        config=ROOT / 'configs/bipiper.yaml', cameras=ROOT / 'configs/cameras.yaml',
        urdf=ROOT / 'assets/piper/piper.urdf', execute=execute, prompt='test',
        checkpoint='dreamlabs/dream-1-beta', action_hz=20., chunks=1, retry_timeout=180.,
        speed_scale=.5, max_joint_speed=30., max_joint_acceleration=120.))
    assert calls['client_closed']
    if execute:
        assert calls['connected'] and calls['disconnected']
        assert len(calls['sent']) == 1 and calls['stopped'] >= 1
        assert 'left_joint1' in calls['sent'][0]
    else:
        assert 'robot_created' not in calls
        assert not calls['sent'] and calls['feedback_closed'] == 2


def test_slow_playback_keeps_rows_and_stretches_large_moves():
    from scripts.dreamlabs import action_interval
    previous = {f'{s}_joint{i}': 0. for s in ('left', 'right') for i in range(1, 7)}
    target = previous.copy()
    assert action_interval(previous, target, 20., .5, 30.) == .1
    target['left_joint1'] = np.deg2rad(60.)
    assert action_interval(previous, target, 20., .5, 30.) == pytest.approx(2.)


def test_reply_log_shows_shapes_and_values(caplog):
    import logging
    from scripts.dreamlabs import log_reply
    with caplog.at_level(logging.INFO, logger='piper.dreamlabs'):
        log_reply({'per_key': {'action.left_eef_xyz': [[.1, .2, .3]], 'action.left_arm': None}})
    assert 'Respuesta recibida' in caplog.text
    assert 'forma=(1, 3)' in caplog.text
    assert 'primera=[0.1, 0.2, 0.3]' in caplog.text
    assert 'action.left_arm: null' in caplog.text


@pytest.mark.parametrize('flag,value', [('--speed-scale', '2'), ('--speed-scale', '0'),
                                       ('--max-joint-speed', 'nan'),
                                       ('--max-joint-acceleration', '-1')])
def test_invalid_speed_cli_rejected(flag, value):
    with pytest.raises(SystemExit) as error:
        main(['--prompt', 'test', flag, value])
    assert error.value.code == 2


if __name__ == '__main__':
    raise SystemExit(main())
