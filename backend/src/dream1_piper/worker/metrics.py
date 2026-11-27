"""Bounded runtime metrics shared by worker, station and operations UI."""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, deque
from typing import Any

import numpy as np


class RuntimeMetrics:
    def __init__(self, window_size: int = 200):
        if window_size < 10:
            raise ValueError("metrics window must be at least 10 samples")
        self._lock = threading.Lock()
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._counts: Counter[str] = Counter()
        self._rejections: Counter[str] = Counter()
        self._queue_high_water = 0
        self._last_inference_at: float | None = None
        self._last_error: str | None = None
        self._last_timing: dict[str, Any] = {}

    def inference(self, latency_s: float, timing: dict[str, Any]) -> None:
        with self._lock:
            self._latencies.append(max(0.0, latency_s) * 1000)
            self._counts["chunks"] += 1
            self._last_inference_at = time.monotonic()
            self._last_timing = dict(timing)
            self._last_error = None

    def count(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[name] += amount

    def rejected(self, reason: str) -> None:
        with self._lock:
            self._counts["rejected_actions"] += 1
            self._rejections[reason] += 1
            self._last_error = reason

    def queue_depth(self, depth: int) -> None:
        with self._lock:
            self._queue_high_water = max(self._queue_high_water, depth)

    def error(self, value: str) -> None:
        with self._lock:
            self._last_error = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = np.asarray(tuple(self._latencies), dtype=float)
            timing = dict(self._last_timing)
            return {
                "samples": int(values.size),
                "inference_last_ms": float(values[-1]) if values.size else None,
                "inference_mean_ms": float(values.mean()) if values.size else None,
                "inference_p50_ms": float(np.percentile(values, 50)) if values.size else None,
                "inference_p95_ms": float(np.percentile(values, 95)) if values.size else None,
                "inference_max_ms": float(values.max()) if values.size else None,
                "timing": timing,
                "rtt_ms": _number(timing.get("rtt_ms")),
                "counts": dict(self._counts),
                "rejections": dict(self._rejections),
                "queue_high_water": self._queue_high_water,
                "worker_heartbeat_age_ms": (
                    (time.monotonic() - self._last_inference_at) * 1000
                    if self._last_inference_at is not None
                    else None
                ),
                "error": self._last_error,
            }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
