"""Rolling playback contracts without cameras, CAN, or a network service."""
from types import SimpleNamespace

import numpy as np
import pytest

import scripts.dreamlabs as loop


def harness(monkeypatch, *, fail_row=None):
    clock = [0.0]
    monkeypatch.setattr(loop, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0] + dt)))
    events = {'requests': [], 'sent': [], 'solved': [], 'stops': [], 'refresh': []}

    class Future:
        def __init__(self, fn):
            self.value = fn()
            self.ready = clock[0] + (.02 if fn.__name__ == 'get_action' else 0)
        def done(self):
            return clock[0] >= self.ready
        def result(self):
            return self.value
        def cancel(self):
            return False

    class Pool:
        def __init__(self, **kwargs):
            pass
        def submit(self, fn):
            return Future(fn)
        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr(loop, 'ThreadPoolExecutor', Pool)

    class Client:
        def get_action(self):
            events['requests'].append((clock[0], len(events['sent'])))
            n = len(events['requests'])
            parts = {}
            for side in loop.SIDES:
                parts[f'action.{side}_eef_xyz'] = [[n * .1 + i * .001, 0, 0] for i in range(12)]
                parts[f'action.{side}_eef_rot6'] = [[1, 0, 0, 0, 1, 0]] * 12
                parts[f'action.{side}_grip'] = [.5] * 12
            return {'per_key': parts}

    class Solver:
        def solve(self, xyz, rotation, seed):
            events['solved'].append(xyz[0])
            if fail_row is not None and xyz[0] >= fail_row:
                raise ValueError('unreachable target')
            return np.full(6, xyz[0]), 0, 0

    robot = SimpleNamespace(
        send_action=lambda action: events['sent'].append((clock[0], action)),
        stop_motion=lambda: events['stops'].append(clock[0]))
    args = SimpleNamespace(action_hz=100., speed_scale=1., replan_rows=4,
                           chunks=3, retry_timeout=2.)
    def run():
        loop.stream_rollout(Client(), {s: Solver() for s in loop.SIDES},
                            lambda: {s: (np.zeros(6), .5) for s in loop.SIDES},
                            lambda: None, robot, args, 100000.,
                            refresh_observation=lambda: events['refresh'].append(clock[0]))
    return run, events


def test_requests_overlap_playback_and_expired_rows_are_not_queued(monkeypatch):
    run, events = harness(monkeypatch)
    run()
    assert len(events['requests']) == len(events['refresh']) == 3
    # Request 2 goes out well before the first horizon's 12 rows finish.
    assert 0 < events['requests'][1][1] < 12
    # Stop only at completion, with no measured-position resets between horizons.
    assert len(events['stops']) == 1
    targets = [a['left_joint1'] for _, a in events['sent']]
    assert any(.202 <= q < .3 for q in targets)
    assert .2 not in targets  # response arrived two rows after request time
    assert len(events['solved']) < 3 * 12 * 2
    times = [t for t, _ in events['sent']]
    assert max(np.diff(times)) < .02


def test_later_ik_failure_stops_before_sending_invalid_row(monkeypatch):
    run, events = harness(monkeypatch, fail_row=.103)
    with pytest.raises(ValueError, match='unreachable'):
        run()
    assert events['sent']
    assert all(a['left_joint1'] < .103 for _, a in events['sent'])
    assert len(events['stops']) == 1


def test_camera_read_does_not_block_action_ticks():
    import threading

    sent = threading.Event()
    captured = threading.Event()
    def observe():
        # The camera can finish only after playback has started.
        assert sent.wait(1), 'camera read blocked playback'
        captured.set()

    class Solver:
        def solve(self, *args):
            return np.zeros(6), 0, 0

    class Client:
        def get_action(self):
            return {'per_key': {f'action.{s}_{p}': [value] * 3
                                for s in loop.SIDES
                                for p, value in [('eef_xyz', [0, 0, 0]),
                                                 ('eef_rot6', [1, 0, 0, 0, 1, 0]),
                                                 ('grip', .5)]}}

    args = SimpleNamespace(action_hz=100., speed_scale=1., replan_rows=8,
                           chunks=1, retry_timeout=1.)
    loop.stream_rollout(Client(), {s: Solver() for s in loop.SIDES},
                        lambda: {s: (np.zeros(6), .5) for s in loop.SIDES},
                        observe, SimpleNamespace(send_action=lambda a: sent.set(),
                                                 stop_motion=lambda: None),
                        args, 30.)
    assert captured.is_set()
