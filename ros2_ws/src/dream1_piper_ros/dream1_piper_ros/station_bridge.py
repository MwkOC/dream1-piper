import asyncio
import json
import os
import threading
import time
from collections import deque

import rclpy
from geometry_msgs.msg import TwistStamped
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectory
try:
    from websockets.asyncio.server import serve
except ImportError:  # ROS Jazzy's Ubuntu package may still provide websockets 10.x.
    from websockets import serve
from dream1_piper_ros.tracking_metrics import (
    match_feedback_target,
    orientation_error_deg,
    position_error_mm,
)


SIDES = ("left", "right")


class StationBridge(Node):
    def __init__(self):
        super().__init__("dream1_piper_station_bridge")
        self.declare_parameter("home_duration_s", 3.0)
        self.declare_parameter("home_tolerance_rad", 0.08)
        self.declare_parameter(
            "pose_metrics_hz", float(os.getenv("RSTACK_POSE_METRICS_HZ", "0.3333333333"))
        )
        self.declare_parameter(
            "pose_metrics_max_target_age_ms",
            float(os.getenv("RSTACK_POSE_METRICS_MAX_TARGET_AGE_MS", "250")),
        )
        self.home_duration_s = float(self.get_parameter("home_duration_s").value)
        self.home_tolerance_rad = float(self.get_parameter("home_tolerance_rad").value)
        self.pose_metrics_hz = float(self.get_parameter("pose_metrics_hz").value)
        self.pose_metrics_max_target_age_s = (
            float(self.get_parameter("pose_metrics_max_target_age_ms").value) / 1000
        )
        if self.pose_metrics_hz <= 0 or self.pose_metrics_max_target_age_s <= 0:
            raise ValueError("pose metric rate and target age must be positive")
        tracking_history_limit = int(os.getenv("RSTACK_MEMORY_HISTORY_LIMIT", "100000"))
        if not 1 <= tracking_history_limit <= 100000:
            raise ValueError("RSTACK_MEMORY_HISTORY_LIMIT must be between 1 and 100000")
        self.lock = threading.RLock()
        self.arms = {side: {"stamp": 0.0, "joints": [], "gripper": 0.0, "tcp": None, "tcp_stamp": 0.0} for side in SIDES}
        self.tracking_targets = {side: deque(maxlen=128) for side in SIDES}
        self.last_pose_metric_at = {side: 0.0 for side in SIDES}
        self.tracking_samples = deque(maxlen=tracking_history_limit)
        self.source = None
        self.selected_arm = None
        self.generation = 0
        self.gates_open = set()
        self.joint_pubs = {}
        self.twist_pubs = {}
        self.gate_clients = {}
        self.enable_clients = {}
        self.arm_subscriptions = []
        for side in SIDES:
            self._create_arm_io(side)
        self.joint_state_pub = self.create_publisher(JointState, "/joint_states", 10)
        self.tracking_pub = self.create_publisher(String, "/dream1/metrics/tcp_tracking", 10)
        self.create_timer(0.01, self._publish_fused_joint_state)

    def _create_arm_io(self, side):
        root = f"/{side}"
        self.joint_pubs[side] = self.create_publisher(JointState, f"{root}/control/joint_states", 5)
        self.twist_pubs[side] = self.create_publisher(TwistStamped, f"{root}/servo_node/delta_twist_cmds", 5)
        self.gate_clients[side] = self.create_client(SetBool, f"{root}/control_enable")
        self.enable_clients[side] = self.create_client(SetBool, f"{root}/enable_agx_arm")
        self.arm_subscriptions.append(self.create_subscription(JointState, f"{root}/feedback/joint_states", lambda msg, arm=side: self._joint_feedback(arm, msg), 20))
        self.arm_subscriptions.append(self.create_subscription(PoseStamped, f"{root}/feedback/tcp_pose", lambda msg, arm=side: self._tcp_feedback(arm, msg), 10))
        self.arm_subscriptions.append(self.create_subscription(JointTrajectory, f"{root}/servo_node/command", lambda msg, arm=side: self._servo_command(arm, msg), 10))

    def _joint_feedback(self, side, message):
        with self.lock:
            positions = list(message.position)
            gripper = positions[6] / 0.1 if len(positions) > 6 else 0.0
            self.arms[side].update({"stamp": time.monotonic(), "joints": positions[:6], "gripper": gripper})

    def _tcp_feedback(self, side, message):
        pose = message.pose
        received_at = time.monotonic()
        # The pinned AgileX driver leaves frame_id empty; feedback uses the
        # arm-local base frame selected by its namespace.
        frame_id = str(message.header.frame_id) or f"{side}_base_link"
        measured = {
            "position": [pose.position.x, pose.position.y, pose.position.z],
            "orientation": [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w],
        }
        sample = None
        with self.lock:
            self.arms[side]["tcp"] = {**measured, "frame_id": frame_id}
            self.arms[side]["tcp_stamp"] = received_at
            feedback_stamp = float(message.header.stamp.sec) + message.header.stamp.nanosec / 1e9
            target = self._match_tracking_target(side, feedback_stamp, received_at)
            if target:
                sample = self._tracking_sample(side, target, measured, frame_id, received_at, message)
                if sample:
                    self.tracking_samples.append(sample)
        if sample:
            self.tracking_pub.publish(String(data=json.dumps(sample)))

    def _match_tracking_target(self, side, feedback_stamp, received_at):
        # Match by the driver's measurement time, not callback arrival order.
        return match_feedback_target(
            self.tracking_targets[side],
            feedback_stamp,
            received_at,
            self.pose_metrics_max_target_age_s,
        )

    def _tracking_sample(self, side, target, measured, frame_id, received_at, message):
        target_pose = target.get("pose")
        if not isinstance(target_pose, dict):
            return None
        age_s = received_at - target["issued_at"]
        feedback_age_s = (
            float(message.header.stamp.sec)
            + message.header.stamp.nanosec / 1e9
            - target["issued_stamp_sec"]
        )
        if age_s < 0 or age_s > self.pose_metrics_max_target_age_s or feedback_age_s < 0:
            return None
        if received_at - self.last_pose_metric_at[side] < 1 / self.pose_metrics_hz:
            return None
        self.last_pose_metric_at[side] = received_at
        if frame_id != target_pose.get("frame_id"):
            return {
                **target["context"], "stage": "tcp_tracking_error", "arm": side,
                "result": "unavailable", "reason": "frame_mismatch",
                "target_frame_id": target_pose.get("frame_id"), "feedback_frame_id": frame_id,
            }
        position_error = position_error_mm(target_pose["position"], measured["position"])
        orientation_error = orientation_error_deg(
            target_pose["orientation"], measured["orientation"]
        )
        stamp = message.header.stamp
        return {
            **target["context"], "stage": "tcp_tracking_error", "arm": side, "result": "measured",
            "position_error_mm": position_error, "orientation_error_deg": orientation_error,
            "target": target_pose, "measured": {**measured, "frame_id": frame_id},
            "target_age_ms": feedback_age_s * 1000,
            "feedback_arrival_age_ms": age_s * 1000,
            "target_stamp_sec": target["issued_stamp_sec"],
            "feedback_stamp_sec": float(stamp.sec) + float(stamp.nanosec) / 1e9,
        }

    def _servo_command(self, side, trajectory):
        with self.lock:
            allowed = self.source == "teleop" and self.selected_arm == side and side in self.gates_open
        if not allowed or not trajectory.points:
            return
        point = trajectory.points[0]
        values = list(point.positions)
        names = [name.removeprefix(f"{side}_") for name in trajectory.joint_names]
        self._publish_joint_state(side, names, values)

    def _publish_fused_joint_state(self):
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        with self.lock:
            for side in SIDES:
                values = self.arms[side]["joints"]
                if len(values) != 6:
                    return
                message.name.extend([f"{side}_joint{index}" for index in range(1, 7)])
                message.position.extend(values)
        self.joint_state_pub.publish(message)

    async def serve(self):
        async with serve(self._handle, "127.0.0.1", 8766, max_size=1024 * 1024):
            self.get_logger().info("ROS station gateway listening on 127.0.0.1:8766")
            await asyncio.Future()

    async def _handle(self, socket, _path=None):
        async for raw in socket:
            try:
                request = json.loads(raw)
                response = await self._dispatch(request)
            except Exception as error:
                response = {"accepted": False, "reason": f"{type(error).__name__}: {error}"}
            await socket.send(json.dumps(response))

    async def _dispatch(self, request):
        kind = request.get("type")
        payload = request.get("payload", {})
        if kind == "status":
            return self._status()
        if kind == "arm":
            return await self._arm(payload)
        if kind == "start":
            return await self._start(payload)
        if kind == "stop":
            return await self._stop(payload)
        if kind == "teleop":
            return self._teleop(payload)
        if kind == "dream_action":
            return self._dream_action(payload)
        if kind == "home":
            return await self._home(payload)
        raise ValueError(f"unknown station command {kind}")

    def _status(self):
        with self.lock:
            arms = {}
            for side in SIDES:
                sample = dict(self.arms[side])
                fresh = time.monotonic() - sample["stamp"] < 0.5 and len(sample["joints"]) == 6
                services = self.enable_clients[side].service_is_ready() and self.gate_clients[side].service_is_ready()
                servo = self.twist_pubs[side].get_subscription_count() > 0
                tcp_fresh = time.monotonic() - sample["tcp_stamp"] < 0.5 and sample["tcp"] is not None
                arms[side] = {"connected": fresh, "servo_ready": servo, "services_ready": services, "state": {"joints": sample["joints"], "gripper": sample["gripper"], "tcp": sample["tcp"], "tcp_fresh": tcp_fresh}}
            ready = all(arm["connected"] and arm["services_ready"] and arm["servo_ready"] for arm in arms.values())
            tracking_samples = list(self.tracking_samples)
            self.tracking_samples.clear()
        return {"accepted": True, "ready": ready, "arms": arms, "tracking_samples": tracking_samples}

    async def _arm(self, payload):
        source = str(payload["source"])
        selected = payload.get("arm")
        if source == "teleop" and selected not in SIDES:
            raise ValueError("teleop arm selection is required")
        sides = SIDES if source == "dream" else (selected,)
        for side in sides:
            if not await asyncio.to_thread(self._call_bool, self.enable_clients[side], True):
                raise RuntimeError(f"failed to enable {side} Piper")
        with self.lock:
            self.source, self.selected_arm = source, selected
            self.generation = int(payload.get("generation", self.generation + 1))
        return {"accepted": True}

    async def _start(self, payload):
        requested_generation = int(payload["generation"])
        if requested_generation != self.generation:
            raise RuntimeError(
                "stale station control generation "
                f"(station={requested_generation}, ros={self.generation})"
            )
        sides = SIDES if self.source == "dream" else (self.selected_arm,)
        for side in sides:
            if not await asyncio.to_thread(self._call_bool, self.gate_clients[side], True):
                raise RuntimeError(f"failed to open {side} command gate")
        with self.lock:
            self.gates_open.update(sides)
        return {"accepted": True}

    async def _stop(self, payload=None):
        payload = payload or {}
        closed = []
        for side in SIDES:
            self._publish_twist_zero(side)
            closed.append(await asyncio.to_thread(self._call_bool, self.gate_clients[side], False))
        with self.lock:
            self.gates_open.clear()
            self.generation = int(payload.get("generation", self.generation + 1))
        if not all(closed):
            raise RuntimeError("one or more ROS control gates did not close")
        return {"accepted": True}

    def _teleop(self, payload):
        side = payload["arm"]
        with self.lock:
            allowed = self.source == "teleop" and self.selected_arm == side and side in self.gates_open
        if not allowed:
            raise RuntimeError("teleop source or driver gate is not active")
        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = f"{side}_base_link"
        message.twist.linear.x, message.twist.linear.y, message.twist.linear.z = payload["linear"]
        message.twist.angular.x, message.twist.angular.y, message.twist.angular.z = payload["angular"]
        self.twist_pubs[side].publish(message)
        return {"accepted": True}

    def _dream_action(self, payload):
        values = payload["values"]
        if len(values) != 14 or int(payload["generation"]) != self.generation:
            raise RuntimeError("invalid action dimension or stale generation")
        with self.lock:
            if self.source != "dream" or not set(SIDES).issubset(self.gates_open):
                raise RuntimeError("Dream source is not active")
        for side, start in (("left", 0), ("right", 7)):
            target_pose = (payload.get("tcp_targets") or {}).get(side)
            issued_at = time.monotonic()
            command_stamp = self.get_clock().now().to_msg()
            issued_stamp_sec = float(command_stamp.sec) + command_stamp.nanosec / 1e9
            with self.lock:
                if isinstance(target_pose, dict):
                    self.tracking_targets[side].append(
                        {
                            "pose": target_pose,
                            "issued_at": issued_at,
                            "issued_stamp_sec": issued_stamp_sec,
                            "context": {
                                "control_source": "dream",
                                "operation_id": payload.get("operation_id"),
                                "session_id": payload.get("session_id"),
                                "sequence": payload.get("sequence_id"),
                                "invocation_id": payload.get("invocation_id"),
                            },
                        }
                    )
            self._publish_joint_state(
                side,
                [*(f"joint{index}" for index in range(1, 7)), "gripper"],
                [*values[start:start + 6], max(0.0, min(1.0, values[start + 6])) * 0.1],
                stamp=command_stamp,
            )
        return {"accepted": True}

    async def _home(self, payload):
        values = payload["values"]
        generation = int(payload.get("generation", self.generation))
        if len(values) != 14:
            raise ValueError("Home target must contain fourteen joint/gripper values")
        enabled = []
        for side in SIDES:
            motor_enabled = await asyncio.to_thread(self._call_bool, self.enable_clients[side], True)
            gate_open = await asyncio.to_thread(self._call_bool, self.gate_clients[side], True)
            enabled.append(motor_enabled and gate_open)
        if not all(enabled):
            await self._stop({"generation": generation})
            raise RuntimeError("could not enable both arms and open both gates for Home")
        with self.lock:
            self.gates_open.update(SIDES)
            self.source = "dream"
            self.generation = generation
        try:
            self._dream_action({"values": values, "generation": self.generation})
            reached = await self._wait_home_target(values)
        finally:
            await self._stop({"generation": generation})
        if not reached:
            raise TimeoutError(f"Home target was not reached within {self.home_duration_s:.1f}s")
        return {"accepted": True, "status": "home target reached"}

    async def _wait_home_target(self, values):
        deadline = time.monotonic() + self.home_duration_s
        while time.monotonic() < deadline:
            with self.lock:
                arms = {side: list(self.arms[side]["joints"]) for side in SIDES}
            if all(
                len(arms[side]) == 6
                and max(
                    abs(actual - target)
                    for actual, target in zip(arms[side], values[start:start + 6], strict=True)
                ) <= self.home_tolerance_rad
                for side, start in (("left", 0), ("right", 7))
            ):
                return True
            await asyncio.sleep(0.05)
        return False

    def _publish_joint_state(self, side, names, values, *, stamp=None):
        if len(names) != len(values):
            raise ValueError("joint target names and values differ in length")
        message = JointState()
        message.header.stamp = stamp or self.get_clock().now().to_msg()
        message.name, message.position = names, values
        self.joint_pubs[side].publish(message)

    def _publish_twist_zero(self, side):
        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = f"{side}_base_link"
        self.twist_pubs[side].publish(message)

    @staticmethod
    def _call_bool(client, value):
        if not client.wait_for_service(timeout_sec=1.0):
            return False
        request = SetBool.Request()
        request.data = value
        response = client.call(request)
        return bool(response and response.success)


def main(args=None):
    rclpy.init(args=args)
    node = StationBridge()
    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()
    try:
        asyncio.run(node.serve())
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
