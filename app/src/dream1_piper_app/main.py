"""FastAPI application with no ROS or Dream runtime imports."""

from fastapi import FastAPI

from .models import ObservationEnvelope, ValidationResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Dream-1 Piper", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/v1/observations/validate", response_model=ValidationResponse)
    def validate_observation(observation: ObservationEnvelope) -> ValidationResponse:
        return ValidationResponse(
            episode_id=observation.episode_id,
            frame_keys=sorted(observation.frames),
            state_keys=sorted(observation.state),
        )

    return app


app = create_app()

