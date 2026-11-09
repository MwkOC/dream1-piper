from pathlib import Path

import numpy as np
import pytest
from piper.kinematics import PiperKinematics

URDF = Path(__file__).parents[1] / "piper" / "assets" / "piper.urdf"


@pytest.mark.parametrize("side", ["left", "right"])
def test_piper_kinematics_accepts_both_urdf_chains(side: str) -> None:
    kin = PiperKinematics(URDF, f"{side}_base_link", f"{side}_tcp", side)
    pose = kin.forward_matrix(np.zeros(6))
    assert pose.shape == (4, 4)
    np.testing.assert_allclose(pose[3], [0.0, 0.0, 0.0, 1.0])


def test_rot6_rejects_degenerate_axes() -> None:
    kin = PiperKinematics(URDF, "left_base_link", "left_tcp", "left")
    with pytest.raises(ValueError, match="degenerate"):
        kin.rot6_to_matrix(np.zeros(6))


def test_ik_reaches_pose_generated_by_forward_kinematics() -> None:
    kin = PiperKinematics(URDF, "left_base_link", "left_tcp", "left")
    joints = np.array([0.1, 0.4, -0.5, 0.2, 0.3, -0.2])
    pose = kin.forward_matrix(joints)
    rot6 = pose[:3, :2].T.reshape(-1)
    solved, position_error, rotation_error = kin.solve(pose[:3, 3], rot6, np.zeros(6))
    assert position_error < 0.02
    assert rotation_error < np.deg2rad(10.0)
    assert np.all(solved >= kin.lower)
    assert np.all(solved <= kin.upper)


def test_ik_rejects_nonfinite_seed() -> None:
    kin = PiperKinematics(URDF, "left_base_link", "left_tcp", "left")
    with pytest.raises(ValueError, match="finite"):
        kin.solve([0.2, 0.0, 0.2], [1, 0, 0, 0, 1, 0], [np.nan] * 6)
