from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder

from app.api.v1.api_router import api_router
from app.core.config import settings
from app.core.errors import ApiError
from app.core.logger import startup_logger
from app.core.responses import error_payload
from app.db.database import close_mongo_connection, connect_to_mongo
from app.core.middlewares.loggerMiddleware import LoggerMiddleware
from app.core.middlewares.auth_middleware import AuthMiddleware
from app.core.middlewares.security_middleware import SecurityMiddleware

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
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
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

settings.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
app.mount(
    "/public/storage",
    StaticFiles(directory=str(settings.STORAGE_ROOT), check_dir=False),
    name="public-storage",
)


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
    """Handle standard FastAPI HTTPException errors."""
    del request
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(message=detail),
    )


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


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    """Health check endpoint."""
    return {"message": "Welcome to Workspace Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
