from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .config import EXPERIMENT_ROOT, RobotConfig, load_robot
from .control import MotionSupervisor, RunState
from .hardware import BiPiper, Cameras
from .metrics import RuntimeMetrics
from .protocol import Observation, observation_message, parse_action
from .settings import env_value


class Station:
    """Hardware owner and the only process allowed to send Piper targets."""

    def __init__(self, config: RobotConfig):
        self.config = config
        self.robot = BiPiper(config)
        self.cameras = Cameras(config.cameras)
        settings = config.station
        self.supervisor = MotionSupervisor(
            config.schema,
            action_age_ms=float(settings["action_age_ms"]),
            scheduled_action_age_ms=float(settings["scheduled_action_age_ms"]),
        )
        self.observation_id = self.accepted_actions = self.rejected_actions = 0
        self.connection: Any | None = None
        self._send_lock = asyncio.Lock()
        self.task = ""
        self.rtc: dict[str, object] = {"enabled": False}
        self.metrics = RuntimeMetrics()
        self.observation_failures = 0
        self.hardware_validated = False
        self._last_control_state: tuple[str, int] | None = None

    def connect(self) -> None:
        self.robot.connect()
        try:
            self.cameras.connect()
            self.config.schema.validate_action(self.robot.observation())
            self.supervisor.connected()
        except BaseException:
            self.robot.disconnect()
            raise

    def disconnect(self) -> None:
        try:
            self.robot.hold()
        except Exception as exc:
            print(f"station shutdown: hold failed: {exc}", file=sys.stderr)
        try:
            self.cameras.disconnect()
        except Exception as exc:
            print(f"station shutdown: camera close failed: {exc}", file=sys.stderr)
        try:
            self.robot.disconnect()
        except Exception as exc:
            print(f"station shutdown: Piper disconnect failed: {exc}", file=sys.stderr)
        finally:
            self.supervisor.state = RunState.DISCONNECTED

    def arm(self) -> str:
        if self.supervisor.state == RunState.DISCONNECTED:
            raise RuntimeError("connect the station before arming")
        if not self.hardware_validated:
            raise RuntimeError("validate robot feedback and camera frames before arming")
        self.config.schema.validate_action(self.robot.observation())
        return self.supervisor.arm()

    def start(self) -> None:
        self.supervisor.start()

    def pause(self, reason: str = "operator pause") -> None:
        try:
            self.robot.hold()
        except Exception as exc:
            self.supervisor.fault(f"{reason}; hold failed: {type(exc).__name__}: {exc}")
            self.hardware_validated = False
            return
        self.supervisor.pause(reason)
        self.hardware_validated = False

    def home(self) -> None:
        """Pause first; the configured home target still uses bounded streamers."""
        self.pause("home requested")
        if self.supervisor.state == RunState.FAULT:
            raise RuntimeError(self.supervisor.last_fault or "could not hold Piper before Home")
        target = tuple(float(value) for value in self.config.station.get("home_action", ()))
        if len(target) != 14:
            raise RuntimeError("home is not configured for this station profile")
        self.config.schema.validate_action(target)
        self.robot.set_target(target)

    def clear_fault(self) -> None:
        self.robot.hold()
        self.supervisor.reset_fault()

    def validate_hardware(self) -> None:
        self.hardware_validated = False
        if self.supervisor.state == RunState.DISCONNECTED:
            raise RuntimeError("connect the station before validation")
        if self.supervisor.state not in {RunState.READY, RunState.PAUSED}:
            raise RuntimeError("pause the station before hardware validation")
        self.config.schema.validate_action(self.robot.observation())
        health = self.cameras.health()
        unavailable = [name for name, camera in health.items() if not camera["connected"] or camera["error"]]
        if unavailable:
            raise RuntimeError(f"camera validation failed: {', '.join(unavailable)}")
        self.cameras.frames(
            max_age_ms=float(self.config.station["camera_max_age_ms"]),
            max_skew_ms=float(self.config.station["camera_max_skew_ms"]),
            sync_wait_ms=float(self.config.station.get("camera_sync_wait_ms", 100)),
        )
        self.hardware_validated = True

    def set_task(self, task: str) -> None:
        if self.supervisor.state not in {RunState.READY, RunState.PAUSED}:
            raise RuntimeError("pause the station before editing the Dream task")
        if not isinstance(task, str) or not task.strip() or len(task.strip()) > 2000:
            raise ValueError("task must contain between 1 and 2000 characters")
        self.task = task.strip()

    def status(self) -> dict[str, object]:
        return {
            "state": self.supervisor.state.value,
            "session_id": self.supervisor.session_id,
            "last_fault": self.supervisor.last_fault,
            "accepted_actions": self.accepted_actions,
            "rejected_actions": self.rejected_actions,
            "control_generation": self.supervisor.control_generation,
            "policy_connected": self.connection is not None,
            "hardware_validated": self.hardware_validated,
            "cameras": self.cameras.health(),
            "rtc": dict(self.rtc),
            "metrics": self.metrics.snapshot(),
            "observation_failures": self.observation_failures,
            "task": self.task,
        }

    def observation(self) -> dict[str, object]:
        self.observation_id += 1
        images = self.cameras.frames(
            max_age_ms=float(self.config.station["camera_max_age_ms"]),
            max_skew_ms=float(self.config.station["camera_max_skew_ms"]),
            sync_wait_ms=float(self.config.station.get("camera_sync_wait_ms", 100)),
        )
        message = observation_message(
            Observation(
                self.observation_id,
                time.monotonic_ns(),
                self.robot.observation(),
                images,
                control_generation=self.supervisor.control_generation,
            )
        )
        message["task"] = self.task
        message["session_id"] = self.supervisor.session_id
        return message

    async def _send(self, message: dict[str, object]) -> None:
        if self.connection is not None:
            async with self._send_lock:
                await self.connection.send(json.dumps(message))

    async def _observation_loop(self) -> None:
        settings = self.config.station
        while self.connection is not None:
            if self.supervisor.watchdog_expired(
                float(settings["watchdog_ms"]), float(settings["first_action_timeout_ms"])
            ):
                self.pause("policy action watchdog expired")
                await self._send_control_state_if_changed()
            if self.supervisor.state == RunState.RUNNING:
                try:
                    observation = self.observation()
                    self.metrics.count("observations")
                    await self._send(observation)
                except Exception as exc:
                    await self._handle_observation_failure(exc)
                    break
            else:
                await self._send_control_state_if_changed()
            await asyncio.sleep(1.0 / self.config.schema.control_hz)

    async def _send_control_state_if_changed(self) -> None:
        state = self.supervisor.state.value
        generation = self.supervisor.control_generation
        current = (state, generation)
        if current != self._last_control_state:
            await self._send({"type": "control_state", "state": state, "control_generation": generation})
            self._last_control_state = current

    async def _handle_observation_failure(self, exc: Exception) -> None:
        reason = f"station observation failed: {type(exc).__name__}: {exc}"
        self.observation_failures += 1
        self.metrics.error(reason)
        try:
            self.pause(reason)
        except Exception as hold_exc:
            self.supervisor.fault(f"{reason}; hold failed: {hold_exc}")
        await self._send({"type": "error", "reason": reason})

    async def _receive_loop(self, websocket: Any, *, observe_only: bool) -> None:
        async for raw in websocket:
            await self._handle_worker_message(json.loads(raw), observe_only=observe_only)

    async def _handle_worker_message(self, message: dict[str, Any], *, observe_only: bool) -> None:
        kind = message.get("type")
        if observe_only and kind == "observation_request":
            await self._send_observation()
        elif kind == "rtc_status":
            self._update_rtc(message)
        elif kind == "action":
            await self._handle_action_message(message, observe_only=observe_only)

    async def _send_observation(self) -> None:
        try:
            await self._send(self.observation())
        except Exception as exc:
            await self._handle_observation_failure(exc)

    def _update_rtc(self, message: dict[str, Any]) -> None:
        fields = {
            "enabled", "queue_depth", "queue_high_water", "underruns",
            "inference_p50_ms", "inference_p95_ms", "inference_max_ms",
            "inference_mean_ms", "inference_last_ms", "samples", "timing",
            "counts", "rejections", "worker_heartbeat_age_ms", "error",
            "dry_run", "pacing_mode", "rtt_ms", "observation_hz",
            "action_hz", "chunks", "task",
        }
        self.rtc = {key: value for key, value in message.items() if key in fields}

    async def _handle_action_message(self, message: dict[str, Any], *, observe_only: bool) -> None:
        if observe_only:
            await self._reject_action("read-only connection cannot send actions")
            return
        if self.supervisor.state != RunState.RUNNING:
            await self._send_control_state_if_changed()
            return
        try:
            action = parse_action(message)
            rejection = self.supervisor.validate(action)
            if rejection is not None:
                await self._reject_action(rejection)
                return
            try:
                self.robot.set_target(action.values)
            except Exception as exc:
                await self._fault_target(exc)
                return
            self.accepted_actions += 1
            self.metrics.count("accepted_actions")
        except Exception as exc:
            await self._reject_action(str(exc))

    async def _fault_target(self, exc: Exception) -> None:
        reason = f"Piper target failed: {type(exc).__name__}: {exc}"
        try:
            self.robot.hold()
        except Exception as hold_exc:
            reason = f"{reason}; hold failed: {hold_exc}"
        self.supervisor.fault(reason)
        self.hardware_validated = False
        await self._reject_action(reason)

    async def _reject_action(self, reason: str) -> None:
        self.rejected_actions += 1
        self.metrics.rejected(reason)
        await self._send({"type": "rejected", "reason": reason})

    async def handle(self, websocket: Any) -> None:
        if self.connection is not None:
            await websocket.close(code=4001, reason="one worker is allowed")
            return
        self.connection = websocket
        try:
            hello = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
            if hello.get("type") != "hello" or int(hello.get("schema_version", -1)) != self.config.schema.version:
                raise ValueError("worker schema does not match station")
            mode = str(hello.get("mode", "control"))
            if mode not in {"observe", "control"}:
                raise ValueError("unsupported worker mode")
            observe_only = mode == "observe"
            await self._send({
                "type": "hello", "schema": self.config.schema.to_dict(), "read_only": observe_only,
                "control_generation": self.supervisor.control_generation,
                **self.status(),
            })
            if observe_only:
                await self._receive_loop(websocket, observe_only=True)
                return
            observations = asyncio.create_task(self._observation_loop())
            receive = asyncio.create_task(self._receive_loop(websocket, observe_only=False))
            done, pending = await asyncio.wait({observations, receive}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
        except Exception as exc:
            print(f"station worker connection failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if self.supervisor.state == RunState.RUNNING:
                self.pause(f"policy link failed: {exc}")
            with contextlib.suppress(Exception):
                await websocket.close(code=1011, reason=str(exc)[:120])
        finally:
            self.connection = None
            if self.supervisor.state == RunState.RUNNING:
                self.pause("policy link disconnected")

    async def serve(self, host: str, port: int) -> None:
        from websockets.asyncio.server import serve
        async with serve(self.handle, host, port, max_size=8 * 1024 * 1024):
            await asyncio.Future()


async def _run_services(
    station: Station, *, host: str, port: int, ui_host: str, ui_port: int, no_ui: bool
) -> None:
    tasks = [asyncio.create_task(station.serve(host, port))]
    server: Any | None = None
    if not no_ui:
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError("install requirements-dream-test.txt or pass --no-ui") from exc
        from .ui import create_app

        class LocalServer(uvicorn.Server):
            def capture_signals(self) -> contextlib.AbstractContextManager[None]:
                return contextlib.nullcontext()

        server = LocalServer(uvicorn.Config(create_app(station), host=ui_host, port=ui_port, log_level="warning"))
        tasks.append(asyncio.create_task(server.serve()))
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        if server is not None:
            server.should_exit = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Piper station")
    parser.add_argument("--config", type=Path, default=EXPERIMENT_ROOT / "config/robot.yaml")
    parser.add_argument("--ui-host", default=str(env_value("RSTACK_DREAM_UI_HOST", "127.0.0.1")))
    parser.add_argument("--ui-port", type=int, default=int(env_value("RSTACK_DREAM_UI_PORT", 8080)))
    parser.add_argument("--no-ui", action="store_true", help="serve only the worker WebSocket")
    args = parser.parse_args(argv)
    station: Station | None = None
    try:
        station = Station(load_robot(args.config))
        station.connect()
        asyncio.run(
            _run_services(
                station,
                host=str(station.config.station["host"]),
                port=int(station.config.station["port"]),
                ui_host=str(args.ui_host),
                ui_port=int(args.ui_port),
                no_ui=bool(args.no_ui),
            )
        )
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"piper-station-worker station: failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if station is not None:
            station.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
