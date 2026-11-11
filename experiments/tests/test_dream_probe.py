import numpy as np
import pytest

from piper.dream_probe import RunLogger, _chunk, _policy_config


def _action(rows: int = 48) -> dict[str, np.ndarray]:
    values = np.zeros((rows, 7), dtype=float)
    values[:, 6] = 0.5
    return {"q_l_chunk": values.copy(), "q_r_chunk": values.copy()}


def test_official_ik_policy_config_is_strict_and_uses_eef_head() -> None:
    config = _policy_config("dreamlabs/dream-1-beta", "/tmp/piper-arm.json")
    assert config["strict"] is True
    assert config["robot"] == "other_embodiment"
    assert config["ik"] == {"arm": "/tmp/piper-arm.json", "head": "eef", "solve": "traj"}
    assert (config["obs_window"], config["obs_fps"], config["action_hz"]) == (9, 5, 30)


def test_chunk_requires_two_seven_column_joint_chunks() -> None:
    chunks = _chunk(_action())
    assert chunks["left"].shape == (48, 7)
    assert chunks["right"].shape == (48, 7)

    with pytest.raises(ValueError, match="missing q_r_chunk"):
        _chunk({"q_l_chunk": np.zeros((48, 7))})

    with pytest.raises(ValueError, match=r"expected \[H, 7\]"):
        _chunk({"q_l_chunk": np.zeros((48, 6)), "q_r_chunk": np.zeros((48, 7))})


def test_chunk_rejects_non_finite_and_invalid_gripper_values() -> None:
    action = _action()
    action["q_l_chunk"][0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _chunk(action)

    action = _action()
    action["q_l_chunk"][0, 6] = 1.1
    with pytest.raises(ValueError, match="outside"):
        _chunk(action)


def test_run_logger_separates_execution_evidence(tmp_path) -> None:
    path = tmp_path / "run.jsonl"
    logger = RunLogger(path)
    logger.write("command", model_action={"left": [0.0]}, commanded={"left": [0.0]})
    logger.close()
    text = path.read_text(encoding="utf-8")
    assert '"event":"command"' in text
    assert '"model_action"' in text
    assert '"commanded"' in text
