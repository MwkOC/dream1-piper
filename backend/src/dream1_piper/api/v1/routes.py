import asyncio
import json
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response as RawResponse
from fastapi.responses import StreamingResponse

from dream1_piper.api.dependencies import require_operator, station
from dream1_piper.domain.contracts import (
    ArmCommand,
    LoginCommand,
    OperationCommand,
    PurgeCommand,
    StatusResponse,
    TaskCommand,
    TaskRecordCommand,
)

router = APIRouter(prefix="/api/v1")


def _translate_error(exc):
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(exc, (RuntimeError, TimeoutError)):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request, service=Depends(station)):
    config = request.app.state.settings
    profile = request.app.state.robot_profile["station"]
    return {
        **service.snapshot(),
        "teleop_limits": {
            "jog_speed_m_s": float(profile["teleop_jog_speed_m_s"]),
            "linear_limit_m_s": float(config.teleop_linear_limit_m_s),
            "angular_limit_rad_s": float(config.teleop_angular_limit_rad_s),
        },
    }


@router.get("/cameras/{name}.jpg")
async def camera_frame(name: str, request: Request):
    if name not in {"left", "top", "right"}:
        raise HTTPException(status_code=404, detail="unknown camera")
    try:
        return RawResponse(request.app.state.cameras.frame(name), media_type="image/jpeg")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/auth/session")
async def create_session(payload: LoginCommand, response: Response, request: Request):
    try:
        cookie = request.app.state.auth.login(payload.operator_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="invalid operator token") from exc
    secure = request.url.scheme == "https" or request.app.state.settings.environment == "production"
    response.set_cookie(
        "rstack_session",
        cookie,
        secure=secure,
        httponly=True,
        samesite="strict",
        max_age=request.app.state.settings.session_ttl_seconds,
    )
    return {"authenticated": True}


@router.get("/auth/session", dependencies=[Depends(require_operator)])
async def get_session():
    return {"authenticated": True}


@router.delete("/auth/session", dependencies=[Depends(require_operator)])
async def delete_session(request: Request, response: Response):
    request.app.state.auth.revoke(request.cookies.get("rstack_session"))
    secure = request.url.scheme == "https" or request.app.state.settings.environment == "production"
    response.delete_cookie("rstack_session", secure=secure, httponly=True, samesite="strict")
    return {"authenticated": False}


@router.post("/validate", dependencies=[Depends(require_operator)])
async def validate(body: OperationCommand, request: Request, service=Depends(station)):
    try:
        hardware = await service.robot_gateway.status()
        if not hardware.get("ready"):
            raise RuntimeError("ROS arm feedback is not ready")
        if not all(arm.get("servo_ready") for arm in hardware.get("arms", {}).values()):
            raise RuntimeError("MoveIt Servo is not ready for both arms")
        config = request.app.state.robot_profile["station"]
        request.app.state.cameras.coherent_frames(
            float(config["camera_max_age_ms"]),
            float(config["camera_max_skew_ms"]),
            float(config.get("camera_sync_wait_ms", 0)),
        )
        return service.validate(body.request_id)
    except (ValueError, RuntimeError) as exc:
        _translate_error(exc)


@router.post("/arm", dependencies=[Depends(require_operator)])
async def arm(body: ArmCommand, request: Request, service=Depends(station)):
    try:
        prior = service._idempotent(body.request_id)
        if prior is not None:
            return prior
        if body.control_source == "dream" and service.dream_mode != "action":
            raise ValueError("Dream worker is read-only because RSTACK_DREAM_MODE=observe")
        request.app.state.worker_bridge.reset_action_reference()
        result = service.arm(body.request_id, body.control_source, body.selected_arm)
        await service.robot_gateway.command(
            "arm", {"source": body.control_source, "arm": body.selected_arm}
        )
        return result
    except (ValueError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError):
            service.fault(str(exc))
        _translate_error(exc)


@router.post("/start", dependencies=[Depends(require_operator)])
async def start(body: OperationCommand, service=Depends(station)):
    try:
        prior = service._idempotent(body.request_id)
        if prior is not None:
            return prior
        if service.state.value != "ARMED":
            raise ValueError("arm the selected control source before start")
        if service.control_source == "teleop" and not service.teleop.deadman_active:
            raise ValueError("manual teleop requires an active deadman before Start")
        result = service.start(body.request_id)
        await service.robot_gateway.command("start", {"generation": service.control_generation})
        return result
    except (ValueError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError):
            service.fault(str(exc))
        _translate_error(exc)


@router.post("/pause", dependencies=[Depends(require_operator)])
async def pause(body: OperationCommand, service=Depends(station)):
    try:
        await service.robot_gateway.command("stop", {"reason": "operator pause"})
        return service.pause(body.request_id)
    except ValueError as exc:
        _translate_error(exc)
    except RuntimeError as exc:
        service.fault(f"pause command failed: {exc}")
        _translate_error(exc)


@router.put("/task", dependencies=[Depends(require_operator)])
async def set_task(body: TaskCommand, request: Request, service=Depends(station)):
    try:
        task = body.task
        if body.task_id:
            saved = await request.app.state.repository.get_task(body.task_id)
            if saved is None:
                raise HTTPException(status_code=404, detail="task not found")
            task = saved["prompt"]
        result = service.set_task(task, body.task_id)
        socket = getattr(request.app.state, "worker_socket", None)
        if socket is not None:
            await socket.send_json({"type": "task", "task": result["task"]})
        return result
    except (ValueError, RuntimeError) as exc:
        _translate_error(exc)


@router.get("/tasks", dependencies=[Depends(require_operator)])
async def list_tasks(request: Request):
    return await request.app.state.repository.list_tasks()


@router.post("/tasks", dependencies=[Depends(require_operator)], status_code=201)
async def create_task(body: TaskRecordCommand, request: Request):
    return await request.app.state.repository.create_task(body.name.strip(), body.prompt.strip())


@router.patch("/tasks/{task_id}", dependencies=[Depends(require_operator)])
async def update_task(task_id: UUID, body: TaskRecordCommand, request: Request):
    result = await request.app.state.repository.update_task(
        task_id, body.name.strip(), body.prompt.strip()
    )
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")
    return result


@router.delete("/tasks/{task_id}", dependencies=[Depends(require_operator)])
async def delete_task(task_id: UUID, request: Request):
    if not await request.app.state.repository.delete_task(task_id):
        raise HTTPException(status_code=404, detail="task not found")
    return {"deleted": True, "task_id": str(task_id)}


@router.get("/operations", dependencies=[Depends(require_operator)])
async def list_operations(request: Request, limit: int = 50, offset: int = 0):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..100 and offset >= 0")
    return await request.app.state.repository.list_operations(limit, offset)


@router.get("/operations/{operation_id}", dependencies=[Depends(require_operator)])
async def operation_detail(operation_id: UUID, request: Request):
    result = await request.app.state.repository.operation_detail(operation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="operation not found")
    return result


@router.delete("/history", dependencies=[Depends(require_operator)])
async def purge_history(body: PurgeCommand, request: Request, service=Depends(station)):
    if body.confirmation != "DELETE ALL DATA":
        raise HTTPException(status_code=422, detail='confirmation must be "DELETE ALL DATA"')
    if service.state.value in {"ARMED", "RUNNING"}:
        raise HTTPException(status_code=409, detail="pause and disarm the station before purging")
    flush = getattr(request.app.state.event_writer, "flush", None)
    if flush:
        try:
            await flush()
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="pending event persistence did not drain"
            ) from exc
    await request.app.state.repository.purge_all()
    request.app.state.event_bus.clear()
    request.app.state.metrics.clear()
    request.app.state.event_writer.dropped = 0
    service.task = ""
    service.task_id = None
    return {"deleted": True}


@router.post("/home", dependencies=[Depends(require_operator)])
async def home(body: OperationCommand, request: Request, service=Depends(station)):
    try:
        if service.state.value not in {"READY", "PAUSED"} or not service.hardware_validated:
            raise ValueError("validate hardware and pause the station before Home")
        await service.robot_gateway.command("stop", {"reason": "home requested"})
        service.pause(body.request_id, "home requested")
        values = request.app.state.robot_profile["station"]["home_action"]
        return await service.robot_gateway.command("home", {"values": values})
    except ValueError as exc:
        _translate_error(exc)
    except (RuntimeError, TimeoutError) as exc:
        service.fault(str(exc))
        _translate_error(exc)


@router.post("/fault/reset", dependencies=[Depends(require_operator)])
async def reset_fault(body: OperationCommand, service=Depends(station)):
    if service.state.value != "FAULT":
        raise HTTPException(status_code=409, detail="station is not in FAULT")
    await service.robot_gateway.command("stop", {"reason": "fault reset"})
    service.last_fault = None
    service.state = service.state.DISCONNECTED
    return {"request_id": str(body.request_id), "accepted": True, **service.snapshot()}


@router.get("/metrics", dependencies=[Depends(require_operator)])
async def get_metrics(request: Request):
    snapshot = request.app.state.metrics.snapshot()
    snapshot["dropped"] += request.app.state.event_writer.dropped
    return snapshot


@router.get("/events", dependencies=[Depends(require_operator)])
async def events(request: Request):
    async def stream():
        queue = request.app.state.event_bus.subscribe()
        try:
            while True:
                item = await queue.get()
                yield f"id: {item['event_id']}\nevent: {item['type']}\ndata: {json.dumps(item)}\n\n"
        finally:
            request.app.state.event_bus.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.websocket("/teleop")
async def teleop(socket: WebSocket):
    origin = socket.headers.get("origin")
    scheme = "https" if socket.url.scheme in {"https", "wss"} else "http"
    expected_origin = f"{scheme}://{socket.url.netloc}"
    if origin and origin.rstrip("/") != expected_origin.rstrip("/"):
        await socket.close(code=4403)
        return
    if not socket.app.state.auth.validate(socket.cookies.get("rstack_session")):
        await socket.close(code=4401)
        return
    await socket.accept()
    try:
        await socket.app.state.teleop.handle(socket)
    except WebSocketDisconnect:
        await socket.app.state.teleop.release("socket disconnected")


@router.websocket("/worker")
async def worker(socket: WebSocket):
    expected = socket.app.state.settings.worker_token
    supplied = socket.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or supplied != expected.get_secret_value():
        await socket.close(code=4401)
        return
    await socket.accept()
    socket.app.state.station.worker_connected = True
    pusher = asyncio.create_task(_push_worker_observations(socket))
    try:
        await socket.send_json(
            {
                "type": "hello",
                "schema": socket.app.state.robot_profile["schema"],
                "read_only": socket.app.state.settings.dream_mode == "observe",
            }
        )
        socket.app.state.worker_socket = socket
        while True:
            message = await socket.receive_json()
            if message.get("type") == "observation_request":
                response = await _worker_observation(socket.app)
            else:
                response = await socket.app.state.worker_bridge.handle(message)
            if response is not None:
                await socket.send_json(response)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await socket.close(code=1011, reason=str(exc)[:120])
    finally:
        pusher.cancel()
        await asyncio.gather(pusher, return_exceptions=True)
        await _worker_disconnected(socket.app)


async def _worker_disconnected(app):
    app.state.station.worker_connected = False
    app.state.worker_socket = None
    active = app.state.station
    if active.state.value != "RUNNING" or active.control_source.value != "dream":
        return
    try:
        await active.robot_gateway.command("stop", {"reason": "worker disconnected"})
    except Exception as exc:
        active.fault(f"worker disconnected; ROS stop failed: {exc}")
        return
    active.pause(uuid4(), "worker disconnected")


async def _worker_observation(app):
    import base64
    import time

    ros = await app.state.ros_gateway.status()
    arms = ros["arms"]
    left = arms["left"]["state"]
    right = arms["right"]["state"]
    values = [*left["joints"], left["gripper"], *right["joints"], right["gripper"]]
    station_config = app.state.robot_profile["station"]
    frames = app.state.cameras.coherent_frames(
        float(station_config["camera_max_age_ms"]),
        float(station_config["camera_max_skew_ms"]),
        float(station_config.get("camera_sync_wait_ms", 0)),
    )
    images = {
        name: base64.b64encode(frames[name]).decode("ascii") for name in ("left", "top", "right")
    }
    return {
        "type": "observation",
        "protocol_version": 1,
        "observation_id": int(time.monotonic_ns()),
        "station_monotonic_ns": time.monotonic_ns(),
        "state": values,
        "images": images,
        "task": app.state.station.task,
        "session_id": app.state.station.session_id,
        "control_generation": app.state.station.control_generation,
    }


async def _push_worker_observations(socket):
    app = socket.app
    previous = None
    last_trace_at = 0.0
    while True:
        station_state = app.state.station
        active_dream = (
            app.state.settings.dream_mode == "action"
            and station_state.state.value == "RUNNING"
            and station_state.control_source.value == "dream"
        )
        if active_dream:
            try:
                observation = await _worker_observation(app)
                await socket.send_json(observation)
                now = asyncio.get_running_loop().time()
                if now - last_trace_at >= 1.0:
                    state_names = app.state.robot_profile["schema"]["state_names"]
                    app.state.event_bus.publish(
                        "observation",
                        {
                            "operation_id": station_state.operation_id,
                            "control_source": "dream",
                            "task": station_state.task,
                            "state": dict(zip(state_names, observation["state"], strict=True)),
                            "observation_id": observation["observation_id"],
                            "cameras": app.state.cameras.health(),
                        },
                    )
                    last_trace_at = now
            except Exception as exc:
                await socket.send_json({"type": "error", "reason": str(exc)})
                try:
                    await app.state.ros_gateway.command(
                        "stop", {"reason": "worker observation failed"}
                    )
                except Exception:
                    pass
                station_state.fault(f"worker observation failed: {exc}")
                return
        else:
            control = (station_state.state.value.lower(), station_state.control_generation)
            if control != previous:
                await socket.send_json(
                    {"type": "control_state", "state": control[0], "control_generation": control[1]}
                )
                previous = control
        await asyncio.sleep(1.0 / app.state.settings.control_hz)
