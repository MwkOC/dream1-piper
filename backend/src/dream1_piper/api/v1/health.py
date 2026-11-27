from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response):
    database_ok = await request.app.state.database.check()
    ros_ok = request.app.state.ros_ready
    camera_ok = request.app.state.camera_ready
    ready = database_ok and ros_ok and camera_ok
    response.status_code = 200 if ready else 503
    return {
        "status": "ready" if ready else "not_ready",
        "database": database_ok,
        "ros": ros_ok,
        "cameras": camera_ok,
    }
