import json
from pathlib import Path

from capture.record_episode import CaptureConfig, build_command, main


def test_capture_command_uses_configured_topics(tmp_path: Path) -> None:
    config_path = tmp_path / "topics.yaml"
    config_path.write_text("storage_id: mcap\ntopics: {camera: /camera/image}\n", encoding="utf-8")
    config = CaptureConfig.from_file(config_path)
    command = build_command(config, tmp_path / "bag")
    assert command[:6] == ["ros2", "bag", "record", "--storage", "mcap", "--output"]
    assert command[-1] == "/camera/image"


def test_capture_dry_run_writes_manifest_without_ros(tmp_path: Path) -> None:
    config_path = tmp_path / "topics.yaml"
    config_path.write_text("topics: {camera: /camera/image}\n", encoding="utf-8")
    output = tmp_path / "episode"
    assert main([
        "--config", str(config_path),
        "--output", str(output),
        "--task", "test task",
        "--dry-run",
    ]) == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task"] == "test task"
    assert manifest["topics"] == {"camera": "/camera/image"}

