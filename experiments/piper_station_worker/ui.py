"""FastAPI operations surface, separated from station state ownership."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .station import Station

def create_app(station: Station) -> Any:
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise RuntimeError("install requirements-dream-test.txt to use the operations UI") from exc
    app = FastAPI(title="Dream-1 Piper experiment", version="0.2.0")
    _register_read_routes(app, station)
    _register_control_routes(app, station)
    return app

def _register_read_routes(app: Any, station: Station) -> None:
    from fastapi import HTTPException, Response
    from fastapi.responses import FileResponse
    index = Path(__file__).resolve().parent / "web" / "index.html"
    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(index)
    @app.get("/api/status")
    def status() -> dict[str, object]:
        return station.status()
    @app.get("/api/cameras/{name}.jpg")
    def camera(name: str) -> Response:
        try:
            return Response(station.cameras.frame(name), media_type="image/jpeg")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

def _register_control_routes(app: Any, station: Station) -> None:
    from fastapi import HTTPException
    def invoke(operation: Any) -> dict[str, object]:
        try:
            result = operation()
            return result if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    @app.post("/api/validate")
    def validate() -> dict[str, object]:
        return invoke(lambda: (station.validate_hardware(), {"ok": True})[1])
    @app.post("/api/task")
    def task(payload: dict[str, object]) -> dict[str, object]:
        return invoke(lambda: _save_task(station, payload))
    @app.post("/api/arm")
    def arm() -> dict[str, object]:
        return invoke(lambda: {"session_id": station.arm()})
    @app.post("/api/start")
    def start() -> dict[str, object]:
        return invoke(lambda: _run_state(station, station.start))
    @app.post("/api/pause")
    def pause() -> dict[str, object]:
        return invoke(lambda: _run_state(station, station.pause))
    @app.post("/api/home")
    def home() -> dict[str, object]:
        return invoke(lambda: _run_state(station, station.home))
    @app.post("/api/reset-fault")
    def reset_fault() -> dict[str, object]:
        return invoke(lambda: _run_state(station, station.clear_fault))

def _save_task(station: Station, payload: dict[str, object]) -> dict[str, object]:
    station.set_task(str(payload.get("task", "")))
    return {"task": station.task}

def _run_state(station: Station, operation: Any) -> dict[str, object]:
    operation()
    return station.status()
