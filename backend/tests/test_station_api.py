from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from dream1_piper.core.settings import Settings
from dream1_piper.main import create_app

ROOT = Path(__file__).resolve().parents[2]


class FakeDatabase:
    async def check(self):
        return True

    async def close(self):
        return None


class FakeEventWriter:
    dropped = 0

    async def start(self):
        return None

    async def close(self):
        return None

    async def flush(self):
        return None

    def submit(self, *_):
        return None


class FakeCameras:
    def start(self):
        return None

    def close(self):
        return None

    def health(self):
        return {name: {"connected": True, "age_ms": 1.0} for name in ("left", "top", "right")}

    def coherent_frames(self, *_):
        return {name: b"jpeg" for name in ("left", "top", "right")}

    def frame(self, _):
        return b"jpeg"


class FakeRosGateway:
    def __init__(self):
        self.commands = []

    async def status(self):
        state = {"joints": [0.0] * 6, "gripper": 0.0, "tcp": None}
        arms = {
            side: {"connected": True, "servo_ready": True, "services_ready": True, "state": state}
            for side in ("left", "right")
        }
        return {"ready": True, "arms": arms}

    async def command(self, kind, payload):
        self.commands.append((kind, payload))
        return {"accepted": True}


class FakeRepository:
    def __init__(self):
        self.tasks = {}
        self.operations = []

    async def list_tasks(self):
        return list(self.tasks.values())

    async def get_task(self, task_id):
        return self.tasks.get(str(task_id))

    async def create_task(self, name, prompt):
        now = datetime.now(UTC).isoformat()
        item = {
            "task_id": str(uuid4()),
            "name": name,
            "prompt": prompt,
            "created_at": now,
            "updated_at": now,
            "enabled": True,
        }
        self.tasks[item["task_id"]] = item
        return item

    async def update_task(self, task_id, name, prompt):
        item = self.tasks.get(str(task_id))
        if item is None:
            return None
        item.update(name=name, prompt=prompt)
        return item

    async def delete_task(self, task_id):
        return self.tasks.pop(str(task_id), None) is not None

    async def list_operations(self, limit, offset):
        return self.operations[offset : offset + limit]

    async def operation_detail(self, operation_id):
        return next(
            (item for item in self.operations if item["operation_id"] == str(operation_id)), None
        )

    async def purge_all(self):
        self.tasks.clear()
        self.operations.clear()


def app_with_fakes(gateway, repository=None):
    settings = Settings(
        _env_file=None,
        environment="development",
        ui_operator_token="operator-token",
        worker_token="worker-token",
        session_secret="test-secret-with-more-than-thirty-two-characters",
        robot_config=str(ROOT / "configs/app_robot.yaml"),
        dream_config=str(ROOT / "experiments/piper_station_worker/config/dream.yaml"),
        frontend_dist=str(ROOT / "missing-frontend-dist"),
    )
    return create_app(
        settings,
        database=FakeDatabase(),
        ros_gateway=gateway,
        cameras=FakeCameras(),
        event_writer=FakeEventWriter(),
        repository=repository or FakeRepository(),
    )


def test_operator_session_and_fastapi_openapi_are_available():
    with TestClient(app_with_fakes(FakeRosGateway())) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/api-docs").status_code == 200
        assert client.get("/api/v1/auth/session").status_code == 401
        response = client.post("/api/v1/auth/session", json={"operator_token": "operator-token"})
        assert response.status_code == 200
        assert client.get("/api/v1/auth/session").json() == {"authenticated": True}


def test_validate_and_teleop_deadman_start_pause_lifecycle():
    gateway = FakeRosGateway()
    with TestClient(app_with_fakes(gateway)) as client:
        client.post("/api/v1/auth/session", json={"operator_token": "operator-token"})
        validated = client.post(
            "/api/v1/validate", json={"request_id": "b6da83e8-ae16-490b-b8c6-2d7aad4e115e"}
        )
        assert validated.status_code == 200
        armed = client.post(
            "/api/v1/arm",
            json={
                "request_id": "b6da83e8-ae16-490b-b8c6-2d7aad4e115f",
                "control_source": "teleop",
                "selected_arm": "left",
            },
        )
        assert armed.status_code == 200
        generation = armed.json()["control_generation"]

        with client.websocket_connect(
            "/api/v1/teleop", headers={"origin": "http://testserver"}
        ) as socket:
            socket.send_json(
                {
                    "type": "heartbeat",
                    "sequence": 1,
                    "control_generation": generation,
                    "arm": "left",
                    "deadman": True,
                    "linear": [0.0, 0.0, 0.0],
                    "angular": [0.0, 0.0, 0.0],
                }
            )
            assert socket.receive_json()["accepted"] is True
            started = client.post(
                "/api/v1/start",
                json={"request_id": "b6da83e8-ae16-490b-b8c6-2d7aad4e1150"},
            )
            assert started.status_code == 200
            assert started.json()["state"] == "RUNNING"
            socket.send_json(
                {
                    "type": "heartbeat",
                    "sequence": 2,
                    "control_generation": generation,
                    "arm": "left",
                    "deadman": False,
                    "linear": [0.0, 0.0, 0.0],
                    "angular": [0.0, 0.0, 0.0],
                }
            )
            assert socket.receive_json()["status"] == "paused"

        status = client.get("/api/v1/status").json()
        assert status["state"] == "PAUSED"
        assert gateway.commands[0][0] == "arm"
        assert any(kind == "start" for kind, _ in gateway.commands)
        assert any(kind == "stop" for kind, _ in gateway.commands)


def test_task_crud_operation_history_and_guarded_full_purge():
    repository = FakeRepository()
    app = app_with_fakes(FakeRosGateway(), repository)
    with TestClient(app) as client:
        client.post("/api/v1/auth/session", json={"operator_token": "operator-token"})
        created = client.post(
            "/api/v1/tasks", json={"name": "Plátano", "prompt": "Llevar el plátano a la cubeta"}
        )
        assert created.status_code == 201
        task = created.json()
        assert client.get("/api/v1/tasks").json()[0]["task_id"] == task["task_id"]
        updated = client.patch(
            f"/api/v1/tasks/{task['task_id']}",
            json={"name": "Tarea banana", "prompt": "Poner el plátano en la cubeta"},
        )
        assert updated.status_code == 200

        app.state.station.state = app.state.station.state.READY
        selected = client.put(
            "/api/v1/task", json={"task_id": task["task_id"], "task": "ignored by server"}
        )
        assert selected.status_code == 200
        assert app.state.station.task == "Poner el plátano en la cubeta"

        operation_id = str(uuid4())
        repository.operations.append(
            {"operation_id": operation_id, "task_snapshot": app.state.station.task}
        )
        assert client.get("/api/v1/operations").json()[0]["operation_id"] == operation_id
        assert client.get(f"/api/v1/operations/{operation_id}").status_code == 200

        app.state.station.state = app.state.station.state.RUNNING
        blocked = client.request(
            "DELETE", "/api/v1/history", json={"confirmation": "DELETE ALL DATA"}
        )
        assert blocked.status_code == 409
        app.state.station.state = app.state.station.state.PAUSED
        purged = client.request(
            "DELETE", "/api/v1/history", json={"confirmation": "DELETE ALL DATA"}
        )
        assert purged.status_code == 200
        assert repository.tasks == {}
        assert repository.operations == []
        assert app.state.station.task == ""
