from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter()


class StorageReadiness(BaseModel):
    backend: Literal["postgres", "memory"]
    persistent: bool


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    database: bool | None
    ros: bool
    cameras: bool
    storage: StorageReadiness


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz", response_model=Readiness)
async def readyz(request: Request, response: Response):
    backend = request.app.state.storage_backend
    database_ok = await request.app.state.database.check() if backend == "postgres" else None
    ros_ok = request.app.state.ros_ready
    camera_ok = request.app.state.camera_ready
    ready = (database_ok is not False) and ros_ok and camera_ok
    response.status_code = 200 if ready else 503
    return {
        "status": "ready" if ready else "not_ready",
        "database": database_ok,
        "storage": {"backend": backend, "persistent": request.app.state.storage_persistent},
        "ros": ros_ok,
        "cameras": camera_ok,
    }
