from fastapi import HTTPException, Request


def station(request: Request):
    return request.app.state.station


def require_operator(request: Request):
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin.rstrip("/") != expected.rstrip("/"):
        raise HTTPException(status_code=403, detail="request origin is not allowed")
    auth = request.app.state.auth
    if not auth.validate(request.cookies.get("rstack_session")):
        raise HTTPException(status_code=401, detail="operator session required")
    return True
