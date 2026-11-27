import math
import time


class WorkerBridge:
    def __init__(
        self, station, gateway, metrics, events, mode, limits, action_names, event_writer=None
    ):
        self.station = station
        self.gateway = gateway
        self.metrics = metrics
        self.events = events
        self.mode = mode
        self.limits = limits
        self.action_names = action_names
        self.last_values = None
        self.last_action_at = None
        self.event_writer = event_writer

    def reset_action_reference(self):
        self.last_values = None
        self.last_action_at = None

    async def handle(self, message):
        kind = message.get("type")
        if kind == "hello":
            return {"type": "hello", "accepted": True, "mode": self.mode}
        if kind == "rtc_status":
            self.events.publish("worker_health", message)
            metric = {
                "control_source": "dream",
                "stage": "inference",
                "duration_ms": message.get("inference_last_ms"),
                "timing": message.get("timing", {}),
                "operation_id": self.station.operation_id,
            }
            self.metrics.record(metric)
            return {"type": "ack", "accepted": True}
        if kind == "metric":
            metric = {
                **message,
                "operation_id": self.station.operation_id,
                "control_source": "dream",
            }
            self.metrics.record(metric)
            if self.event_writer:
                self.event_writer.submit("metric", metric)
            self.events.publish("metric", metric)
            return {"type": "ack", "accepted": True}
        if kind == "invocation":
            invocation = {
                **message,
                "operation_id": self.station.operation_id,
                "control_source": "dream",
            }
            if self.event_writer:
                self.event_writer.submit("policy_invocation", invocation)
            self.events.publish("invocation", {"stage": "inference", **invocation})
            return {"type": "ack", "accepted": True}
        if kind != "action":
            return {"type": "ack", "accepted": False, "reason": "unsupported worker message"}
        return await self._handle_action(message)

    async def _handle_action(self, message):
        rejection = self._action_rejection(message)
        if rejection:
            rejected = {
                "control_source": "dream",
                "operation_id": self.station.operation_id,
                "sequence": message.get("sequence_id"),
                "result": "rejected",
                "reason": rejection,
                "proposed": {
                    "values": message.get("values", []),
                    "named": self._named_values(message.get("values", []))
                    if isinstance(message.get("values"), list)
                    else {},
                },
            }
            self.events.publish("action", rejected)
            if self.event_writer and self.station.operation_id:
                self.event_writer.submit("action", rejected)
            return {"type": "ack", "accepted": False, "reason": rejection}
        values = message["values"]
        feedback = await self.gateway.command(
            "dream_action",
            {
                "values": values,
                "generation": self.station.control_generation,
                "tcp_targets": message.get("tcp_targets", {}),
                "session_id": message.get("session_id"),
                "sequence_id": message.get("sequence_id"),
                "invocation_id": message.get("invocation_id"),
                "operation_id": (
                    str(self.station.operation_id) if self.station.operation_id else None
                ),
            },
        )
        self.last_values = list(values)
        self.last_action_at = time.monotonic()
        action = self._action_record(message, values)
        action["proposed"]["named"] = self._named_values(values)
        action["applied"]["named"] = self._named_values(values)
        action["applied"]["tcp_targets"] = message.get("tcp_targets", {})
        action["feedback"] = feedback if isinstance(feedback, dict) else {}
        self._record_action(action)
        return {"type": "ack", "accepted": True, "action_id": message.get("action_id")}

    def _action_rejection(self, message):
        if self.mode != "action" or self.station.state.value != "RUNNING":
            return "station is not accepting Dream actions"
        if self.station.control_source.value != "dream":
            return "Dream is not the active source"
        values = message.get("values")
        if not isinstance(values, list) or len(values) != 14:
            return "expected fourteen joint/gripper values"
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            return "action contains invalid numeric values"
        if int(message.get("control_generation", -1)) != self.station.control_generation:
            return "stale control generation"
        return self._validate_limits(values)

    def _action_record(self, message, values):
        return {
            "control_source": "dream",
            "action_id": message.get("action_id"),
            "sequence": message.get("sequence_id"),
            "invocation_id": message.get("invocation_id"),
            "operation_id": self.station.operation_id,
            "result": "accepted",
            "proposed": {"values": values},
            "applied": {"values": values},
            "feedback": {},
        }

    def _named_values(self, values):
        return dict(zip(self.action_names, values, strict=False))

    def _record_action(self, action):
        self.metrics.record(action)
        self.events.publish("action", action)
        if self.event_writer:
            self.event_writer.submit("action", action)

    def _validate_limits(self, values):
        now = time.monotonic()
        elapsed = max(0.001, now - self.last_action_at) if self.last_action_at else 1.0
        if len(self.limits) != 14:
            return "station profile must define fourteen joint limits"
        for index, (value, limits) in enumerate(zip(values, self.limits, strict=True)):
            if not limits["minimum"] <= value <= limits["maximum"]:
                return f"action index {index} is outside configured position limits"
            if (
                self.last_values is not None
                and abs(value - self.last_values[index]) > limits["max_speed"] * elapsed * 1.5
            ):
                return f"action index {index} exceeds configured joint speed"
        return None
