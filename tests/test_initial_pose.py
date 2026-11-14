from pathlib import Path

import numpy as np

from scripts.constants import PIPER_JOINT_LOWER_RAD, PIPER_JOINT_UPPER_RAD
from scripts.initial_pose import load_piper_initial_joint_pose
from scripts.kinematics import PiperKinematics


def test_default_pose_is_shared_in_range_and_slightly_raised():
    pose = load_piper_initial_joint_pose()
    np.testing.assert_array_equal(pose.joints['left'], pose.joints['right'])
    assert not np.shares_memory(pose.joints['left'], pose.joints['right'])
    for side, joints in pose.joints.items():
        assert np.all(joints >= PIPER_JOINT_LOWER_RAD)
        assert np.all(joints <= PIPER_JOINT_UPPER_RAD)
        solver = PiperKinematics(Path(__file__).resolve().parents[1] / 'assets/piper/piper.urdf',
                                 f'{side}_base_link', f'{side}_tcp', side)
        rise = solver.forward_matrix(joints)[2, 3] - solver.forward_matrix(np.zeros(6))[2, 3]
        assert 0.02 < rise < 0.04
