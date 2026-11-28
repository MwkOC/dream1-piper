import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import add_scalar_reference

from dream1_piper.adapters.cameras import CameraInput
from dream1_piper.adapters.memory import MemoryEventWriter, MemoryRepository, MemoryStore
from dream1_piper.adapters.postgres.database import Database
from dream1_piper.adapters.postgres.event_writer import EventWriter
from dream1_piper.adapters.postgres.repository import StationRepository
from dream1_piper.adapters.ros_gateway import RosGateway
from dream1_piper.api.v1.health import router as health_router
from dream1_piper.api.v1.routes import router as api_router
from dream1_piper.core.settings import PROJECT_ROOT, Settings, get_settings
from dream1_piper.domain.contracts import RunState
from dream1_piper.services.auth import SessionAuth
from dream1_piper.services.events import EventBus, MetricsService
from dream1_piper.services.station import StationService
from dream1_piper.services.teleop import TeleopService
from dream1_piper.services.worker_bridge import WorkerBridge


def _event_sink(app, event_type, data):
    data = jsonable_encoder(data)
    item = app.state.event_bus.publish(event_type, data)
    app.state.metrics.record({"type": event_type, **data})
    app.state.event_writer.submit(event_type, {"event_id": item["event_id"], **data})


async def _probe_ros(app):
    while True:
        was_ready = app.state.ros_ready
        try:
            result = await app.state.ros_gateway.status()
            _consume_tracking_samples(app, result)
            app.state.ros_ready = bool(result.get("ready"))
            if app.state.ros_ready:
                if app.state.station.state.value == "DISCONNECTED":
                    app.state.station.state = RunState.READY
                app.state.station.arms = result.get("arms", app.state.station.arms)
                app.state.station.cameras = app.state.cameras.health()
                app.state.camera_ready = all(
                    item["connected"] for item in app.state.station.cameras.values()
                )
            if was_ready and not app.state.ros_ready:
                await _stop_after_ros_loss(app)
        except Exception as exc:
            app.state.ros_ready = False
            app.state.ros_error = str(exc)
            if was_ready:
                await _stop_after_ros_loss(app)
        await asyncio.sleep(1.0)


def _consume_tracking_samples(app, result):
    for sample in result.get("tracking_samples", []):
        if sample.get("result") == "measured":
            sample["operation_id"] = sample.get("operation_id") or app.state.station.operation_id
        _event_sink(app, "metric", sample)


async def _stop_after_ros_loss(app):
    async with app.state.control_lock:
        if app.state.station.state not in {RunState.ARMED, RunState.RUNNING}:
            return
        try:
            await app.state.ros_gateway.command(
                "stop",
                {
                    "reason": "ROS feedback lost",
                    "generation": app.state.station.control_generation + 1,
                },
            )
        except Exception:
            pass
        app.state.station.fault("ROS arm feedback lost")


def _install_static_frontend(app, dist_path):
    if not dist_path.is_dir() or not (dist_path / "index.html").is_file():
        return
    app.mount("/assets", StaticFiles(directory=dist_path / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        candidate = (dist_path / path).resolve()
        if candidate.is_relative_to(dist_path.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist_path / "index.html")


def create_app(
    settings: Settings | None = None,
    *,
    database=None,
    ros_gateway=None,
    cameras=None,
    event_writer=None,
    repository=None,
) -> FastAPI:
    config = settings or get_settings()
    config.validate_deployment()
    app = FastAPI(
        title=config.app_name,
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.router.lifespan_context = _make_lifespan(
        config, database, ros_gateway, cameras, event_writer, repository
    )
    app.include_router(health_router)
    app.include_router(api_router)
    add_scalar_reference(app, route="/api-docs")
    _install_static_frontend(app, _project_path(config.frontend_dist))
    return app


def _make_lifespan(config, database, ros_gateway, cameras, event_writer, repository):
    @asynccontextmanager
    async def lifespan(application):
        _initialize_resources(
            application, config, database, ros_gateway, cameras, event_writer, repository
        )
        if application.state.database is not None:
            if not await application.state.database.check():
                await application.state.database.close()
                raise RuntimeError("PostgreSQL unavailable")
        if config.storage_backend == "postgres":
            saved = await application.state.repository.get_selection()
            if saved is not None:
                application.state.station.task = saved["task"]
                application.state.station.task_id = saved.get("task_id")
            for sample in await application.state.repository.recent_metrics(config.memory_history_limit):
                application.state.metrics.record(sample)
        await application.state.event_writer.start()
        probe = asyncio.create_task(_probe_ros(application))
        try:
            yield
        finally:
            await _shutdown(application, probe)

    return lifespan


def _initialize_resources(
    application, config, database, ros_gateway, cameras, event_writer, repository
):
    application.state.settings = config
    application.state.control_lock = asyncio.Lock()
    application.state.storage_backend = config.storage_backend
    application.state.storage_persistent = config.storage_backend == "postgres"
    memory_store = None
    if config.storage_backend == "memory":
        memory_store = MemoryStore(config.memory_history_limit)
        application.state.database = None
    else:
        application.state.database = database or Database(config.database_url.get_secret_value(), config)
    application.state.event_bus = EventBus(history_size=config.memory_history_limit)
    application.state.metrics = MetricsService(config.memory_history_limit)
    application.state.event_writer = event_writer or _event_writer(
        config, application.state.database, memory_store
    )
    application.state.repository = repository or _repository(
        config, application.state.database, memory_store
    )
    application.state.auth = SessionAuth(
        config.ui_operator_token.get_secret_value() if config.ui_operator_token else None,
        config.session_secret.get_secret_value(),
        config.session_ttl_seconds,
    )
    application.state.ros_gateway = ros_gateway or RosGateway(config.ros_bridge_url)
    _initialize_profile(application, config, cameras)
    _initialize_services(application, config)


def _event_writer(config, database, memory_store):
    if config.storage_backend == "memory":
        return MemoryEventWriter(memory_store, config.metrics_queue_size)
    return EventWriter(database, config.metrics_queue_size)


def _repository(config, database, memory_store):
    if config.storage_backend == "memory":
        return MemoryRepository(memory_store)
    return StationRepository(database)


def _initialize_profile(application, config, camera_input=None):
    profile_path = _project_path(config.robot_config)
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["robot"]["options"]["left_port"] = (
        config.can_left or profile["robot"]["options"]["left_port"]
    )
    profile["robot"]["options"]["right_port"] = (
        config.can_right or profile["robot"]["options"]["right_port"]
    )
    overrides = {
        "left": config.camera_left_device,
        "top": config.camera_top_device,
        "right": config.camera_right_device,
    }
    cameras = profile["cameras"]
    for camera in cameras:
        if overrides[camera["name"]]:
            camera["device"] = overrides[camera["name"]]
    application.state.robot_profile = profile
    application.state.cameras = camera_input or CameraInput(cameras)
    try:
        application.state.cameras.start()
    except Exception as exc:
        application.state.camera_error = str(exc)
    application.state.ros_ready = False
    application.state.camera_ready = False
    application.state.ros_error = "ROS bridge has not reported ready"


def _initialize_services(application, config):
    application.state.station = StationService(
        lambda kind, data: _event_sink(application, kind, data), application.state.ros_gateway
    )
    application.state.station.dream_mode = config.dream_mode
    application.state.station.task = config.dream_task or _initial_task(config)
    application.state.teleop = TeleopService(
        application.state.station,
        application.state.ros_gateway,
        config,
        application.state.metrics,
        application.state.event_bus,
        application.state.event_writer,
    )
    application.state.station.teleop = application.state.teleop
    application.state.worker_bridge = WorkerBridge(
        application.state.station,
        application.state.ros_gateway,
        application.state.metrics,
        application.state.event_bus,
        config.dream_mode,
        application.state.robot_profile["schema"]["joint_limits"],
        application.state.robot_profile["schema"]["action_names"],
        application.state.event_writer,
    )


async def _shutdown(application, probe):
    probe.cancel()
    await asyncio.gather(probe, return_exceptions=True)
    application.state.cameras.close()
    try:
        await application.state.event_writer.close()
    finally:
        if application.state.database is not None:
            await application.state.database.close()


def _project_path(value):
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def _initial_task(config):
    source = _project_path(config.dream_config)
    dream_profile = yaml.safe_load(source.read_text(encoding="utf-8"))
    return str(dream_profile.get("task", ""))


app = create_app()


def run():
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "dream1_piper.main:app",
        host=settings.ui_host,
        port=settings.ui_port,
        ssl_certfile=settings.ui_tls_cert,
        ssl_keyfile=settings.ui_tls_key,
    )
