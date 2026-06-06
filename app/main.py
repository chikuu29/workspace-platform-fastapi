from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder

from app.api.v1.api_router import api_router
from app.core.config import settings
from app.core.errors import ApiError
from app.core.logger import startup_logger
from app.core.responses import error_payload
from app.core.database import close_db, connect_db
from app.core.middlewares.loggerMiddleware import LoggerMiddleware
from app.core.middlewares.auth_middleware import AuthMiddleware
from app.core.middlewares.security_middleware import SecurityMiddleware
from app.modules.health.router import router as health_router
from prometheus_fastapi_instrumentator import Instrumentator

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — connect/disconnect MongoDB."""
    startup_logger.info(
        "Starting %s (version: %s) on port %s in %s environment",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.PORT,
        settings.ENV,
    )
    startup_logger.debug("Loaded Settings: %s", settings.model_dump())
    await connect_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    # root_path is required for Swagger/OpenAPI to generate correct URLs
    # through the reverse-proxy (Vite strips /backend, nginx strips /api).
    # NOTE: root_path breaks StaticFiles mounts in Starlette ≥ 0.50, so
    # uploaded files are served via a regular FileResponse route instead.
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
)


if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ── Public Storage (uploaded files) ────────────────────────────────────────
# We serve uploaded files via a regular route instead of StaticFiles mount
# because root_path shifts ASGI scope["path"] in Starlette ≥ 0.50, which
# silently 404s every StaticFiles mount.  A @app.get route goes through
# FastAPI's router and is immune to the root_path path-shift.
settings.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


@app.get("/public/storage/{file_path:path}", include_in_schema=False)
async def serve_storage_file(file_path: str):
    """Serve uploaded files from the storage directory."""
    # Resolve and ensure the path stays within STORAGE_ROOT (prevent traversal)
    resolved = (settings.STORAGE_ROOT / file_path).resolve()
    if not resolved.is_relative_to(settings.STORAGE_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved)


# ── Exception Handlers ────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Format Pydantic validation errors into a structured response."""
    del request
    format_error: dict = {}
    input_captured = False

    for error in exc.errors():
        # Capture input once from the first error that has it
        if not input_captured and "input" in error:
            format_error["input"] = error["input"]
            input_captured = True

        if len(error["loc"]) < 2:
            if "body" not in format_error:
                format_error["body"] = {}
            format_error["body"]["__root__"] = {
                "type": error.get("type"),
                "msg": error.get("msg"),
            }
            continue

        loc_root = str(error["loc"][0])
        field_name = str(error["loc"][-1])

        if loc_root not in format_error:
            format_error[loc_root] = {}

        format_error[loc_root][field_name] = {
            key: error[key]
            for key in error
            if key not in ["loc", "input", "ctx", "url"]
        }

    return JSONResponse(
        content=jsonable_encoder({
            "success": False,
            "message": "Validation Errors",
            "error": format_error,
        }),
        status_code=400,
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    """Handle application-specific API errors."""
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            message=exc.message, errors=exc.errors, payload=exc.payload
        ),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle standard FastAPI HTTPException errors.

    If detail is already a structured dict (from app.common.responses helpers),
    pass it through directly. Otherwise wrap the plain string in error_payload.
    """
    del request

    if isinstance(exc.detail, dict):
        # Structured error — already has { success, message, details }
        content = exc.detail
    else:
        # Legacy plain-string detail — wrap in standard shape
        content = error_payload(message=str(exc.detail))

    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — returns 500."""
    del request
    startup_logger.error("Unhandled exception: %s", str(exc), exc_info=True)
    return JSONResponse(
        content=jsonable_encoder({
            "success": False,
            "message": "Internal Server Error",
            "error": {"detail": str(exc)},
        }),
        status_code=500,
    )


# ── Middleware Registration ────────────────────────────────────────────────────
# Order matters: last added = first to execute
# So: LoggerMiddleware runs first → AuthMiddleware runs second → route handler

# app.add_middleware(AuthMiddleware)
app.add_middleware(LoggerMiddleware)
app.add_middleware(SecurityMiddleware)


# ── API v1 routes (require auth via middleware) ────────────────────────────
app.include_router(api_router, prefix=settings.API_V1_STR)

# ── Health & Observability (no auth — must be reachable by K8s probes) ────
# Registered at root path so liveness/readiness probes work without tokens.
app.include_router(health_router)

# ── Prometheus Metrics ─────────────────────────────────────────────────────
# Expose /metrics for Prometheus scraping. Registered LAST so all routes
# are instrumented, including health endpoints above.
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Welcome to Workspace Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
