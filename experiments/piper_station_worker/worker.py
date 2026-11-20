"""CLI entrypoint and protocol handshake for the Piper Dream worker."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from websockets.asyncio.client import connect
from .config import EXPERIMENT_ROOT, DreamConfig, RobotConfig, load_dream, load_robot
from .control import RobotSchema
from .dream_policy import DreamPiperPolicy, validate_dream_schema
from .worker_helpers import retryable as _retryable, validate_action as _validate_action
from .worker_runtime import WorkerRuntime

def _policy_config(config: DreamConfig) -> dict[str, Any]:
    video = {role: f"observation.images.{local}" for local, role in config.camera_roles.items()}
    state = {
        "right_arm": [0, 6], "right_gripper": [6, 7], "left_arm": [7, 13],
        "left_gripper": [13, 14], "right_eef_xyz": [14, 17],
        "right_eef_rot6": [17, 23], "right_grip": [23, 24],
        "left_eef_xyz": [24, 27], "left_eef_rot6": [27, 33], "left_grip": [33, 34],
    }
    return {"robot": "other_embodiment", "embodiment": {"state": state, "video": video}}

def _observation_payload(state: tuple[float, ...], task: str) -> dict[str, Any]:
    if len(state) != 14:
        raise ValueError("Piper station must provide fourteen state values")
    return {
        "state.right_arm": list(state[7:13]), "state.right_gripper": [state[13]],
        "state.right_grip": [state[13]], "state.left_arm": list(state[:6]),
        "state.left_gripper": [state[6]], "state.left_grip": [state[6]], "prompt": task,
    }

def _fresh_chunk_rows(rows: list[tuple[float, ...]], *, elapsed_s: float, action_hz: float) -> list[tuple[float, ...]]:
    skipped = min(len(rows), max(0, round(elapsed_s * action_hz)))
    if skipped >= len(rows):
        raise TimeoutError("Dream chunk landed after its complete action horizon")
    return rows[skipped:]

async def run(config: DreamConfig, robot: RobotConfig, *, policy: Any | None = None) -> None:
    owned = policy is None
    active_policy = DreamPiperPolicy(config) if policy is None else policy
    try:
        async with connect(config.station_url, max_size=8 * 1024 * 1024) as websocket:
            await _handshake(websocket, active_policy, config, robot.schema)
    finally:
        if owned:
            active_policy.close()

async def _handshake(websocket: Any, policy: Any, config: DreamConfig, schema: RobotSchema) -> None:
    mode = "observe" if config.dry_run else "control"
    await websocket.send(json.dumps({"type": "hello", "schema_version": schema.version, "mode": mode}))
    hello = json.loads(await websocket.recv())
    remote_schema = RobotSchema.from_dict(hello["schema"])
    validate_dream_schema(remote_schema, config)
    if bool(hello.get("read_only")) != config.dry_run:
        raise RuntimeError("station connection mode does not match RSTACK_DREAM_MODE")
    await WorkerRuntime(websocket, policy, remote_schema, observe=config.dry_run).run()

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Dream Piper worker")
    parser.add_argument("--config", type=Path, default=EXPERIMENT_ROOT / "config/dream.yaml")
    parser.add_argument("--robot-config", type=Path, default=EXPERIMENT_ROOT / "config/robot.yaml")
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(load_dream(args.config), load_robot(args.robot_config)))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"piper-station-worker worker: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
