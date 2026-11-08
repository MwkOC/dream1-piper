"""Record a raw ROS 2 episode without implementing a policy or robot control.

The script intentionally delegates serialization and storage to the ROS 2 CLI.
It only validates the configured topic map, writes a manifest, and controls the
recording process lifecycle.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

import yaml


@dataclass(frozen=True)
class CaptureConfig:
    topics: dict[str, str]
    storage_id: str = "mcap"

    @classmethod
    def from_file(cls, path: Path) -> "CaptureConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        topics = raw.get("topics")
        if not isinstance(topics, dict) or not topics:
            raise ValueError("capture config must define a non-empty topics mapping")
        normalized = {str(role): str(topic) for role, topic in topics.items()}
        if any(not role or not topic.startswith("/") for role, topic in normalized.items()):
            raise ValueError("every topic role must map to an absolute ROS topic")
        storage_id = str(raw.get("storage_id", "mcap"))
        return cls(topics=normalized, storage_id=storage_id)


def build_command(config: CaptureConfig, output_bag: Path) -> list[str]:
    return [
        "ros2",
        "bag",
        "record",
        "--storage",
        config.storage_id,
        "--output",
        str(output_bag),
        *config.topics.values(),
    ]


def _topic_list() -> set[str]:
    result = subprocess.run(
        ["ros2", "topic", "list"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def validate_topics(config: CaptureConfig) -> None:
    available = _topic_list()
    missing = sorted(set(config.topics.values()) - available)
    if missing:
        raise RuntimeError(f"configured ROS topics are unavailable: {', '.join(missing)}")


def write_manifest(
    output_dir: Path,
    *,
    config_path: Path,
    config: CaptureConfig,
    episode_id: str,
    task: str,
    ros_domain_id: str | None,
) -> Path:
    manifest = {
        "episode_id": episode_id,
        "task": task,
        "created_unix_s": time.time(),
        "ros_domain_id": ros_domain_id,
        "storage_id": config.storage_id,
        "config": str(config_path.resolve()),
        "topics": config.topics,
        "timestamps": {
            "clock": "host wall clock for manifest; message timestamps remain in the ROS bag",
            "capture_start_unix_s": None,
            "capture_end_unix_s": None,
        },
        "calibration": {},
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _update_manifest(path: Path, start: float, end: float) -> None:
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    manifest["timestamps"]["capture_start_unix_s"] = start
    manifest["timestamps"]["capture_end_unix_s"] = end
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def record(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    config = CaptureConfig.from_file(config_path)
    if args.duration <= 0:
        raise ValueError("duration must be positive")
    if not args.task.strip():
        raise ValueError("task must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    episode_id = args.episode_id or output_dir.name
    manifest_path = write_manifest(
        output_dir,
        config_path=config_path,
        config=config,
        episode_id=episode_id,
        task=args.task,
        ros_domain_id=args.ros_domain_id,
    )
    command = build_command(config, output_dir / "bag")
    print(" ".join(command))

    if args.dry_run:
        return 0
    if shutil.which("ros2") is None:
        raise RuntimeError("ros2 executable not found; source ROS 2 Humble first")
    if not args.skip_topic_validation:
        validate_topics(config)

    environment = None
    if args.ros_domain_id is not None:
        environment = dict(os.environ, ROS_DOMAIN_ID=args.ros_domain_id)
    process = subprocess.Popen(command, env=environment)
    started = time.time()
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        _update_manifest(manifest_path, started, time.time())
    return process.returncode or 0


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="YAML topic map")
    parser.add_argument("--output", required=True, help="episode output directory")
    parser.add_argument("--task", required=True, help="human task prompt")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--episode-id")
    parser.add_argument("--ros-domain-id")
    parser.add_argument("--skip-topic-validation", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return record(parser().parse_args(argv))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"record-piper-episode: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

