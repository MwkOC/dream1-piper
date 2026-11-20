import pytest

from scripts.joint_calibration import load_piper_joint_calibrations


def _document(*, confirmed: bool) -> str:
    return f"""\
schema_version: 1
kind: piper_joint_calibration
confirmed: {str(confirmed).lower()}
arms:
  left:
    signs: [1, -1, 1, 1, 1, 1]
    offsets_rad: [0, 0, -6.283185307179586, 0, 0, 0]
  right:
    signs: [1, 1, 1, 1, 1, 1]
    offsets_rad: [0, 0, 0, 0, 0, 0]
"""


def test_joint_calibration_file_requires_human_confirmation(tmp_path):
    path = tmp_path / "joint-calibration.yaml"
    path.write_text(_document(confirmed=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="not confirmed"):
        load_piper_joint_calibrations(path)


def test_confirmed_joint_calibration_loads_both_arms(tmp_path):
    path = tmp_path / "joint-calibration.yaml"
    path.write_text(_document(confirmed=True), encoding="utf-8")

    calibrations = load_piper_joint_calibrations(path)
    assert set(calibrations) == {"left", "right"}
    assert calibrations["left"].source.endswith("(left)")
