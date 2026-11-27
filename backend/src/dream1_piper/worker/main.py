import argparse
import asyncio
import json
import os
import ssl
from pathlib import Path

from websockets.asyncio.client import connect

from .config import EXPERIMENT_ROOT, load_dream, load_robot
from .control import RobotSchema
from .dream_policy import DreamPiperPolicy, validate_dream_schema
from .worker_runtime import WorkerRuntime


async def run_worker(config, robot, token):
    policy = DreamPiperPolicy(config)
    try:
        await _connect_worker(config, robot.schema, policy, token)
    finally:
        policy.close()


async def _connect_worker(config, schema, policy, token):
    headers = {"Authorization": f"Bearer {token}"}
    tls = _tls_context() if config.station_url.startswith("wss:") else None
    async with connect(
        config.station_url, additional_headers=headers, ssl=tls, max_size=8 * 1024 * 1024
    ) as socket:
        await socket.send(
            json.dumps(
                {
                    "type": "hello",
                    "schema_version": schema.version,
                    "mode": "observe" if config.dry_run else "control",
                }
            )
        )
        hello = json.loads(await socket.recv())
        remote = RobotSchema.from_dict(hello["schema"])
        validate_dream_schema(remote, config)
        if bool(hello.get("read_only")) != config.dry_run:
            raise RuntimeError("station mode differs from RSTACK_DREAM_MODE")
        await WorkerRuntime(socket, policy, remote, observe=config.dry_run).run()


def _tls_context():
    certificate = os.environ.get("RSTACK_UI_CA_CERT")
    return ssl.create_default_context(cafile=certificate)


def _load_local_env():
    from dotenv import load_dotenv

    root_env = Path(__file__).resolve().parents[4] / ".env"
    load_dotenv(root_env, override=False)


def main(argv=None):
    _load_local_env()
    parser = argparse.ArgumentParser(description="Dream-1 bimanual Piper worker")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.getenv("RSTACK_DREAM_CONFIG", EXPERIMENT_ROOT / "config/dream.yaml")),
    )
    parser.add_argument(
        "--robot-config",
        type=Path,
        default=Path(os.getenv("RSTACK_ROBOT_CONFIG", "configs/app_robot.yaml")),
    )
    args = parser.parse_args(argv)
    token = os.getenv("RSTACK_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("RSTACK_WORKER_TOKEN is required")
    asyncio.run(run_worker(load_dream(args.config), load_robot(args.robot_config), token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
