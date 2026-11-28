from datetime import UTC, datetime
from uuid import uuid4

from dream1_piper.domain.contracts import ControlSource, RunState


class StationService:
    """Owns the control state machine; hardware is accessed only through its gateway."""

    def __init__(self, event_sink=None, robot_gateway=None):
        self.state = RunState.DISCONNECTED
        self.control_generation = 0
        self.session_id = None
        self.operation_id = None
        self.control_source = None
        self.selected_arm = None
        self.task = ""
        self.task_id = None
        self.hardware_validated = False
        self.worker_connected = False
        self.arms = {"left": {"connected": False}, "right": {"connected": False}}
        self.cameras = {
            name: {"connected": False, "age_ms": None} for name in ("left", "top", "right")
        }
        self.last_fault = None
        self.event_sink = event_sink or (lambda *_: None)
        self.robot_gateway = robot_gateway
        self._requests = {}

    def snapshot(self):
        return {
            "state": self.state,
            "session_id": self.session_id,
            "operation_id": self.operation_id,
            "control_generation": self.control_generation,
            "control_source": self.control_source,
            "selected_arm": self.selected_arm,
            "task": self.task,
            "hardware_validated": self.hardware_validated,
            "worker_connected": self.worker_connected,
            "arms": self.arms,
            "cameras": self.cameras,
            "last_fault": self.last_fault,
        }

    def validate(self, request_id):
        prior = self._idempotent(request_id)
        if prior is not None:
            return prior
        if self.state not in {RunState.READY, RunState.PAUSED}:
            raise ValueError(f"cannot validate station in {self.state}")
        if not all(item.get("connected") for item in self.arms.values()):
            raise RuntimeError("both ROS arm drivers must be connected before validation")
        if not all(item.get("connected") for item in self.cameras.values()):
            raise RuntimeError("all configured cameras must be connected before validation")
        self.hardware_validated = True
        self.state = RunState.READY
        return self._accepted(request_id)

    def arm(self, request_id, source, selected_arm=None):
        prior = self._idempotent(request_id)
        if prior is not None:
            return prior
        source = ControlSource(source)
        if self.state not in {RunState.READY, RunState.PAUSED} or not self.hardware_validated:
            raise ValueError("validate hardware before arming")
        if source == ControlSource.TELEOP and selected_arm not in {"left", "right"}:
            raise ValueError("manual teleoperation requires exactly one selected arm")
        if source == ControlSource.DREAM and not self.worker_connected:
            raise ValueError("Dream worker is not connected")
        self.control_generation += 1
        self.session_id = str(uuid4())
        self.control_source = source
        self.selected_arm = selected_arm
        self.state = RunState.ARMED
        return self._accepted(request_id)

    def start(self, request_id):
        prior = self._idempotent(request_id)
        if prior is not None:
            return prior
        if self.state != RunState.ARMED:
            raise ValueError("arm the selected control source before start")
        self.state = RunState.RUNNING
        self.operation_id = str(uuid4())
        self._event(
            "operation.started",
            {
                "source": self.control_source,
                "task": self.task,
                "task_id": self.task_id,
                "selected_arm": self.selected_arm,
            },
        )
        return self._accepted(request_id)

    def pause(self, request_id, reason="operator pause"):
        prior = self._idempotent(request_id)
        if prior is not None:
            return prior
        if self.state in {RunState.DISCONNECTED, RunState.FAULT}:
            raise ValueError(f"cannot pause station in {self.state}")
        self.control_generation += 1
        self.state = RunState.PAUSED
        self._event("operation.paused", {"reason": reason})
        return self._accepted(request_id)

    def set_task(self, task, task_id=None):
        if self.state not in {RunState.READY, RunState.PAUSED}:
            raise ValueError("task can only change while READY or PAUSED")
        self.task = task.strip()
        self.task_id = task_id
        return self.snapshot()

    def fault(self, reason):
        self.control_generation += 1
        self.state = RunState.FAULT
        self.last_fault = reason
        self.hardware_validated = False
        self._event("fault", {"reason": reason})

    def _accepted(self, request_id):
        result = {"request_id": str(request_id), "accepted": True, **self.snapshot()}
        self._requests[str(request_id)] = result
        self._event("status", result)
        return result

    def _idempotent(self, request_id):
        return self._requests.get(str(request_id))

    def _event(self, name, data):
        enriched = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": self.session_id,
            "operation_id": self.operation_id,
            "control_source": self.control_source,
            "selected_arm": self.selected_arm,
            **data,
        }
        self.event_sink(name, enriched)
