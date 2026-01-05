from __future__ import annotations


import logging
import time
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles


from app.core.observability import (
    setup_logging, 
    request_id_ctx, 
    new_request_id, 
    get_request_id,
)

from app.api.v1.router import api_router

setup_logging()
logger = logging.getLogger("app")

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.middleware("http")
async def add_request_id_and_timing(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or new_request_id()
    token = request_id_ctx.set(rid)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        status_code = getattr(response, "status_code", 500)

        logger.info(
            "request_complete",
            extra={
                "event": "request_complete",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(elapsed_ms, 2),
                "client": request.client.host if request.client else None,
            },
        )

        request_id_ctx.reset(token)

    response.headers["X-Request-ID"] = rid
    return response

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    rid = get_request_id()
    logger.warning(
        "http_exception",
        extra={
            "event": "http_exception",
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
            "detail": exc.detail if isinstance(exc.detail, str) else None,
        },
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": rid})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = get_request_id()
    logger.exception(
        "unhandled_exception",
        extra={"event": "unhandled_exception", "method": request.method, "path": request.url.path},
    )
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor.", "request_id": rid})

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# API versionada
app.include_router(api_router, prefix="/api/v1")