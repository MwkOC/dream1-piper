from fastapi.testclient import TestClient

from dream1_piper_app.main import app


client = TestClient(app)


def test_health_and_readiness() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_observation_validation() -> None:
    response = client.post(
        "/v1/observations/validate",
        json={
            "episode_id": "episode-1",
            "timestamp_ns": 10,
            "task": "pick up the object",
            "frames": {"video.overhead": "encoded-frame"},
            "state": {"state.left_arm": [0.0] * 6},
        },
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_observation_rejects_nonfinite_state() -> None:
    response = client.post(
        "/v1/observations/validate",
        json={
            "episode_id": "episode-1",
            "timestamp_ns": 10,
            "task": "pick up the object",
            "frames": {"video.overhead": "encoded-frame"},
            "state": {"state.left_arm": ["NaN"]},
        },
    )
    assert response.status_code == 422

