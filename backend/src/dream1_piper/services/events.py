import asyncio
from collections import deque
from math import ceil
from uuid import uuid4


class EventBus:
    def __init__(self, history_size=500, subscriber_size=200):
        self.history = deque(maxlen=history_size)
        self.subscribers = set()
        self.subscriber_size = subscriber_size

    def publish(self, event_type, data):
        item = {"event_id": str(uuid4()), "type": event_type, "data": data}
        self.history.append(item)
        for queue in tuple(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(item)
        return item

    def subscribe(self):
        queue = asyncio.Queue(self.subscriber_size)
        self.subscribers.add(queue)
        for event in self.history:
            if not queue.full():
                queue.put_nowait(event)
        return queue

    def unsubscribe(self, queue):
        self.subscribers.discard(queue)

    def clear(self):
        self.history.clear()
        for queue in tuple(self.subscribers):
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break


class MetricsService:
    def __init__(self):
        self.samples = deque(maxlen=10000)
        self.dropped = 0

    def record(self, metric):
        self.samples.append(metric)

    def clear(self):
        self.samples.clear()
        self.dropped = 0

    def snapshot(self):
        by_source = {"dream": 0, "teleop": 0, "home": 0}
        stages = {}
        tracking = {"left": [], "right": []}
        for sample in self.samples:
            source = sample.get("control_source")
            if source in by_source:
                by_source[source] += 1
            duration = sample.get("duration_ms")
            stage = sample.get("stage")
            if stage and isinstance(duration, (int, float)):
                stages.setdefault(f"{source or 'system'}.{stage}", []).append(float(duration))
            if stage == "tcp_tracking_error" and sample.get("result") == "measured":
                arm = sample.get("arm")
                if arm in tracking and isinstance(sample.get("position_error_mm"), (int, float)):
                    tracking[arm].append(sample)
        return {
            "window_ms": None,
            "sample_count": len(self.samples),
            "by_source": by_source,
            "stages": {name: self._summary(values) for name, values in stages.items()},
            "tcp_tracking": {
                arm: self._tracking_summary(values) for arm, values in tracking.items()
            },
            "dropped": self.dropped,
        }

    @staticmethod
    def _tracking_summary(samples):
        values = [float(sample["position_error_mm"]) for sample in samples]
        ordered = sorted(values)
        median = (
            (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2
            if ordered
            else None
        )
        p95 = ordered[max(0, ceil(len(ordered) * 0.95) - 1)] if ordered else None
        return {
            "sample_count": len(values),
            "mean_mm": sum(values) / len(values) if values else None,
            "median_mm": median,
            "p95_mm": p95,
            "last_mm": values[-1] if values else None,
            "last_orientation_error_deg": (
                samples[-1].get("orientation_error_deg") if samples else None
            ),
            "last_target_age_ms": samples[-1].get("target_age_ms") if samples else None,
        }

    @staticmethod
    def _summary(values):
        ordered = sorted(values)
        if len(ordered) < 2:
            return {
                "sample_count": len(ordered),
                "mean_ms": None,
                "median_ms": None,
                "p95_ms": None,
                "last_ms": ordered[-1] if ordered else None,
            }
        p95 = ordered[max(0, ceil(len(ordered) * 0.95) - 1)]
        median = (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2
        return {
            "sample_count": len(ordered),
            "mean_ms": sum(ordered) / len(ordered),
            "median_ms": median,
            "p95_ms": p95,
            "last_ms": values[-1],
        }
