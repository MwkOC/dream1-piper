"""Interactively measure and persist both Piper gripper travel limits.

The script deliberately connects in feedback-only mode and never sends a
gripper or arm command. Move each gripper with the approved/manual procedure,
then press Enter when it is fully closed or fully open.

Usage:
    python tests/test_gripper_calibration.py
    python tests/test_gripper_calibration.py --samples 25
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
import sys
import time

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.driver import PiperGripperRange  # noqa: E402
from scripts.gripper_calibration import (  # noqa: E402
    save_piper_gripper_calibrations,
)


DEFAULT_OUTPUT = Path("~/.dreamlabs/bipiper-gripper-calibration.yaml")


class PiperGripperReader:
    """Read one Piper gripper without enabling the arm or sending commands."""

    def __init__(self, port: str) -> None:
        try:
            from piper_sdk import C_PiperInterface_V2
        except ImportError as exc:
            raise RuntimeError("piper_sdk is required for gripper calibration") from exc

        self.port = port
        self.arm = C_PiperInterface_V2(port)
        self.arm.ConnectPort(piper_init=False)

    def wait_for_feedback(self, timeout_s: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            feedback = self.arm.GetArmGripperMsgs()
            if float(getattr(feedback, "time_stamp", 0.0)) > 0.0:
                return
            time.sleep(0.02)
        raise TimeoutError(f"{self.port}: no gripper feedback received")

    def read_micrometers(self) -> int:
        feedback = self.arm.GetArmGripperMsgs()
        if float(getattr(feedback, "time_stamp", 0.0)) <= 0.0:
            raise RuntimeError(f"{self.port}: gripper feedback is not ready")
        return int(round(float(feedback.gripper_state.grippers_angle)))

    def sdk_range_micrometers(self) -> tuple[int, int] | None:
        try:
            minimum, maximum = self.arm.GetSDKGripperRangeParam()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        return int(round(float(minimum) * 1_000_000.0)), int(round(float(maximum) * 1_000_000.0))

    def close(self) -> None:
        self.arm.DisconnectPort()


def read_samples(reader: PiperGripperReader, count: int) -> int:
    values = []
    for _ in range(count):
        values.append(reader.read_micrometers())
        time.sleep(0.02)
    return int(round(float(np.median(values))))


def measure_side(side: str, reader: PiperGripperReader, samples: int) -> PiperGripperRange:
    reader.wait_for_feedback()
    sdk_range = reader.sdk_range_micrometers()
    current = reader.read_micrometers()
    print(f"\n[{side}] puerto {reader.port}; lectura actual: {current} microm")
    if sdk_range is not None:
        print(f"[{side}] rango nominal informado por SDK: {sdk_range[0]}..{sdk_range[1]} microm")

    input(f"[{side}] Coloca la pinza TOTALMENTE CERRADA y pulsa Enter...")
    closed = read_samples(reader, samples)
    print(f"[{side}] cerrado medido: {closed} microm")

    input(f"[{side}] Coloca la pinza TOTALMENTE ABIERTA y pulsa Enter...")
    opened = read_samples(reader, samples)
    print(f"[{side}] abierto medido: {opened} microm")

    if opened <= closed:
        raise ValueError(
            f"{side}: el valor abierto ({opened}) debe ser mayor que el cerrado ({closed})"
        )
    return PiperGripperRange(closed, opened, source="measured calibration")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/bipiper.yaml")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=15, help="Samples per endpoint")
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("--samples must be at least 3")

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    robot = config["robot"]
    ports = {"left": robot["left_port"], "right": robot["right_port"]}
    output = args.output.expanduser()

    print("Calibración de grippers Piper (solo lectura; no se envían movimientos).")
    print(f"Se guardará en: {output}")
    print("Mantén despejada el área de trabajo y mueve las pinzas con el procedimiento seguro de tu hardware.")

    readers: dict[str, PiperGripperReader] = {}
    calibrations: dict[str, PiperGripperRange] = {}
    try:
        with ExitStack() as stack:
            for side, port in ports.items():
                readers[side] = PiperGripperReader(port)
                stack.callback(readers[side].close)
            for side in ("left", "right"):
                calibrations[side] = measure_side(side, readers[side], args.samples)
        saved = save_piper_gripper_calibrations(calibrations, output)
    except (KeyboardInterrupt, EOFError):
        print("\nCalibración cancelada; no se guardaron cambios.")
        return

    print(f"\nCalibración guardada en {saved}")
    for side, calibration in calibrations.items():
        print(
            f"  {side}: closed_microm={calibration.min_microm}, "
            f"open_microm={calibration.max_microm}"
        )


if __name__ == "__main__":
    main()
