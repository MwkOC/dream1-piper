from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dream1_piper.core.settings import Settings
from dream1_piper.main import create_app

ROOT = Path(__file__).resolve().parents[2]


class ReadyRosGateway:
    async def status(self):
        return {"ready": True, "arms": {}}


class ReadyCameras:
    def start(self):
        return None

    def close(self):
        return None

    def health(self):
        return {name: {"connected": True} for name in ("left", "top", "right")}


def memory_settings(**overrides):
    values = {
        "_env_file": None,
        "environment": "development",
        "storage_backend": "memory",
        "memory_history_limit": 3,
        "ui_operator_token": "operator-token",
        "session_secret": "test-secret-with-more-than-thirty-two-characters",
        "robot_config": str(ROOT / "configs/app_robot.yaml"),
        "dream_config": str(ROOT / "experiments/piper_station_worker/config/dream.yaml"),
        "frontend_dist": str(ROOT / "missing-frontend-dist"),
    }
    values.update(overrides)
    return Settings(**values)


def test_memory_backend_is_rejected_in_production():
    with pytest.raises(ValueError, match="not allowed in production"):
        memory_settings(environment="production").validate_deployment()


def test_memory_backend_serves_crud_history_and_readiness_without_database(monkeypatch):
    def no_database(*_):
        raise AssertionError("memory backend must not construct a database engine")

    monkeypatch.setattr("dream1_piper.main.Database", no_database)
    app = create_app(
        memory_settings(),
        ros_gateway=ReadyRosGateway(),
        cameras=ReadyCameras(),
    )
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/session", json={"operator_token": "operator-token"}
            ).status_code
            == 200
        )
        readiness = client.get("/readyz")
        assert readiness.status_code == 200
        assert readiness.json()["database"] is None
        assert readiness.json()["storage"] == {"backend": "memory", "persistent": False}

        created = client.post("/api/v1/tasks", json={"name": "Mover", "prompt": "Mover el objeto"})
        assert created.status_code == 201
        task = created.json()
        assert client.get("/api/v1/tasks").json()[0]["task_id"] == task["task_id"]
        task_id = task["task_id"]
        assert (
            client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"name": "Mover actualizado", "prompt": "Ponerlo en la cubeta"},
            ).status_code
            == 200
        )
        assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 200


def test_memory_history_retention_and_purge_clear_collections():
    import asyncio

    from dream1_piper.adapters.memory import MemoryEventWriter, MemoryRepository, MemoryStore

    async def scenario():
        store = MemoryStore(history_limit=2)
        repository = MemoryRepository(store)
        writer = MemoryEventWriter(store, capacity=10)
        await writer.start()
        operation_ids = [str(uuid4()) for _ in range(3)]
        for operation_id in operation_ids:
            writer.submit("operation.started", {"operation_id": operation_id})
        writer.submit("action", {"operation_id": operation_ids[-1], "proposed": {"x": 1}})
        writer.submit("metric", {"operation_id": operation_ids[-1], "stage": "motion"})
        await writer.flush()
        assert len(await repository.list_operations(limit=10, offset=0)) == 2
        detail = await repository.operation_detail(operation_ids[-1])
        assert len(detail["actions"]) == 1
        assert len(detail["metrics"]) == 1
        assert writer.dropped > 0
        await repository.purge_all()
        assert await repository.list_operations(limit=10, offset=0) == []
        assert writer.dropped == 0
        await writer.close()

    asyncio.run(scenario())
