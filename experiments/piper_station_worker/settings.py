"""Environment loading and validated runtime overrides for the experiment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


def environment() -> dict[str, str]:
    """Merge project .env with exported process variables; exports win."""
    values = dotenv_values(Path.cwd() / ".env")
    merged = {key: str(value) for key, value in values.items() if value is not None}
    merged.update(os.environ)
    return merged


def resolve_mode(config: dict[str, Any], *, override: bool | None = None) -> str:
    if override is not None:
        return "observe" if override else "action"
    env = environment()
    mode = env.get("RSTACK_DREAM_MODE")
    if mode is None:
        mode = config.get("mode")
    if mode is None and "dry_run" in config:
        mode = "observe" if bool(config["dry_run"]) else "action"
    mode = str(mode or "action").strip().lower()
    if mode not in {"action", "observe"}:
        raise ValueError("RSTACK_DREAM_MODE must be 'action' or 'observe'")
    return mode


def env_value(key: str, fallback: Any) -> Any:
    return environment().get(key, fallback)
