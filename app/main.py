from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


from app.api.v1.api_router import api_router
from app.core.config import settings
from app.core.errors import ApiError
from app.core.responses import error_payload
from app.db.database import close_mongo_connection, connect_to_mongo
from app.core.response import ResponseHandler
from app.core.middlewares.loggerMiddleware import LoggerMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
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


# Exception handling for FastAPI
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return ResponseHandler.handle_exception(request, exc)

@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(message=exc.message, errors=exc.errors, payload=exc.payload),
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    del request
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(message=detail),
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return ResponseHandler.handle_exception(request, exc)

app.add_middleware(LoggerMiddleware)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"message": "Welcome to Workspace Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=7000, reload=True)
