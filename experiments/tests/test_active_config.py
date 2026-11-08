from pathlib import Path

from piper.active_config import PiperConfig
from piper.active_robot import BiPiperConfig, registered_robot_types


def test_extracted_piper_config_is_bimanual() -> None:
    config = PiperConfig.from_file(Path(__file__).parents[1] / "piper" / "hardware_config.yaml")
    assert config.robot_id == "bi_piper"
    assert (config.left_port, config.right_port) == ("can0", "can1")
    assert set(config.cameras) == {"left", "right", "top"}
    assert config.frames["left_tcp"] == "left_tcp"


def test_bi_piper_is_registered_locally() -> None:
    config = BiPiperConfig()
    assert config.load().robot_id == "bi_piper"
    assert "bi_piper" in registered_robot_types()
