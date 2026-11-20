from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from scripts.driver import PiperJointStreamer, PiperSdkArm
from scripts.joint_calibration import load_piper_joint_calibrations

from .config import Camera, RobotConfig


def _crop(frame: np.ndarray, mode: str) -> np.ndarray:
    if mode.startswith("left_half"):
        frame = frame[:, : frame.shape[1] // 2]
    if mode.endswith("center_16_9"):
        target = 16 / 9
        height, width = frame.shape[:2]
        if width / height > target:
            width = round(height * target)
            offset = (frame.shape[1] - width) // 2
            frame = frame[:, offset : offset + width]
        else:
            height = round(width / target)
            offset = (frame.shape[0] - height) // 2
            frame = frame[offset : offset + height, :]
    return frame


class Cameras:
    """One bounded latest-frame loop per V4L device."""

    def __init__(self, configs: tuple[Camera, ...]):
        self.configs = configs
        self._captures: dict[str, object] = {}
        self._frames: dict[str, tuple[int, bytes]] = {}
        self._errors: dict[str, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def connect(self) -> None:
        import cv2

        try:
            for config in self.configs:
                capture = cv2.VideoCapture(config.device, cv2.CAP_V4L2)
                if not capture.isOpened():
                    raise RuntimeError(f"cannot open {config.name} camera at {config.device}")
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.source_width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.source_height)
                capture.set(cv2.CAP_PROP_FPS, config.fps)
                capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.fourcc))
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._captures[config.name] = capture
                thread = threading.Thread(target=self._run, args=(config,), daemon=True, name=f"camera-{config.name}")
                thread.start()
                self._threads.append(thread)
        except BaseException:
            self.disconnect()
            raise

    def _run(self, config: Camera) -> None:
        import cv2

        capture = self._captures[config.name]
        while not self._stop.is_set():
            ok, frame = capture.read()
            if not ok:
                with self._lock:
                    self._errors[config.name] = "camera read failed"
                self._stop.wait(0.03)
                continue
            if frame.shape[:2] != (config.source_height, config.source_width):
                with self._lock:
                    self._errors[config.name] = f"source shape {frame.shape[1]}x{frame.shape[0]} is unexpected"
                continue
            frame = cv2.resize(_crop(frame, config.crop), (config.width, config.height), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality])
            if not ok:
                continue
            with self._lock:
                self._frames[config.name] = (time.monotonic_ns(), encoded.tobytes())
                self._errors.pop(config.name, None)

    def frames(
        self, *, max_age_ms: float, max_skew_ms: float, sync_wait_ms: float = 0.0
    ) -> dict[str, bytes]:
        """Return a latest-frame set within the hard skew bound.

        Independent UVC capture threads can briefly straddle a frame boundary.
        A short retry window selects the next coherent set without weakening the
        configured skew contract.
        """
        deadline = time.monotonic() + max(0.0, sync_wait_ms) / 1_000.0
        last_error = "camera frames unavailable"
        while True:
            with self._lock:
                snapshot = dict(self._frames)
                errors = dict(self._errors)
            missing = set(config.name for config in self.configs) - set(snapshot)
            if missing or errors:
                last_error = f"camera frames unavailable: {sorted(missing)} {errors}"
            else:
                now = time.monotonic_ns()
                ages = {
                    name: (now - timestamp) / 1_000_000
                    for name, (timestamp, _) in snapshot.items()
                }
                if max(ages.values()) > max_age_ms:
                    last_error = f"stale camera frame: {ages}"
                else:
                    stamps = [timestamp for timestamp, _ in snapshot.values()]
                    skew_ms = (max(stamps) - min(stamps)) / 1_000_000
                    if skew_ms <= max_skew_ms:
                        return {name: payload for name, (_, payload) in snapshot.items()}
                    last_error = (
                        f"camera frames exceed allowed skew: {skew_ms:.1f} ms > "
                        f"{max_skew_ms:.1f} ms; ages_ms="
                        f"{{{', '.join(f'{name}: {age:.1f}' for name, age in ages.items())}}}"
                    )
            if time.monotonic() >= deadline:
                raise RuntimeError(last_error)
            self._stop.wait(min(0.005, max(0.0, deadline - time.monotonic())))

    def disconnect(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1.0)
        for capture in self._captures.values():
            capture.release()
        self._captures.clear()

    def health(self) -> dict[str, dict[str, object]]:
        now = time.monotonic_ns()
        with self._lock:
            return {
                config.name: {
                    "connected": config.name in self._frames,
                    "age_ms": (
                        (now - self._frames[config.name][0]) / 1_000_000
                        if config.name in self._frames
                        else None
                    ),
                    "error": self._errors.get(config.name),
                    "shape": [config.width, config.height],
                }
                for config in self.configs
            }

    def frame(self, name: str) -> bytes:
        with self._lock:
            try:
                return self._frames[name][1]
            except KeyError as exc:
                raise KeyError(f"camera {name!r} has no frame") from exc


class BiPiper:
    """Source-profile Piper driver: left seven values followed by right seven."""

    def __init__(self, config: RobotConfig):
        self.config = config
        self.left: PiperSdkArm | None = None
        self.right: PiperSdkArm | None = None
        self.streamers: tuple[PiperJointStreamer, PiperJointStreamer] | None = None

    def connect(self) -> None:
        options = self.config.options
        calibrations = load_piper_joint_calibrations(
            options.get("joint_calibration_path")
        )
        try:
            self.left = PiperSdkArm(
                str(options["left_port"]),
                startup_speed_percent=int(options["startup_speed_percent"]),
                speed_percent=int(options["motion_speed_percent"]),
                enable_timeout_s=float(options["enable_timeout_s"]),
                gripper_effort=int(options["gripper_effort"]),
                joint_calibration=calibrations["left"],
            )
            self.right = PiperSdkArm(
                str(options["right_port"]),
                startup_speed_percent=int(options["startup_speed_percent"]),
                speed_percent=int(options["motion_speed_percent"]),
                enable_timeout_s=float(options["enable_timeout_s"]),
                gripper_effort=int(options["gripper_effort"]),
                joint_calibration=calibrations["right"],
            )
            rate = float(self.config.station["stream_rate_hz"])
            speed = float(self.config.station["stream_max_joint_speed_deg_s"])
            acceleration = float(self.config.station["stream_max_joint_acceleration_deg_s2"])
            self.streamers = (
                PiperJointStreamer(self.left, command_rate_hz=rate, max_joint_speed_deg_s=speed, max_joint_acceleration_deg_s2=acceleration),
                PiperJointStreamer(self.right, command_rate_hz=rate, max_joint_speed_deg_s=speed, max_joint_acceleration_deg_s2=acceleration),
            )
            for streamer in self.streamers:
                streamer.start()
        except BaseException:
            self.disconnect()
            raise

    def observation(self) -> tuple[float, ...]:
        if self.left is None or self.right is None:
            raise RuntimeError("Piper is disconnected")
        left_grip, right_grip = self.left.read_gripper_opening(), self.right.read_gripper_opening()
        if left_grip is None or right_grip is None:
            raise RuntimeError("Piper gripper feedback is unavailable")
        return tuple(self.left.read_joints_rad()) + (left_grip,) + tuple(self.right.read_joints_rad()) + (right_grip,)

    def set_target(self, values: tuple[float, ...]) -> None:
        if self.streamers is None or len(values) != 14:
            raise RuntimeError("invalid target or disconnected Piper")
        self.streamers[0].set_target(np.asarray(values[:6]), values[6])
        self.streamers[1].set_target(np.asarray(values[7:13]), values[13])

    def hold(self) -> None:
        self.set_target(self.observation())

    def disconnect(self) -> None:
        try:
            if self.streamers is not None:
                for streamer in self.streamers:
                    streamer.stop()
        finally:
            self.streamers = None
            for arm in (self.right, self.left):
                if arm is not None:
                    arm.disconnect()
            self.left = self.right = None
