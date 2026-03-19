import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies import RequestContext, get_current_user, require_request_context
from app.core.config import settings
from app.core.errors import ApiError
from app.core.responses import success_response
from app.db.database import get_database

router = APIRouter()


def _create_upload_name(original_name: str) -> str:
    original_path = Path(original_name)
    suffix = original_path.suffix
    stem = original_path.stem or "file"
    return f"{int(time.time() * 1000)}-{stem}{suffix}"


@router.get("/ui_template")
async def get_template(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    query = dict(request.query_params)
    template = await db["template"].find(query).to_list(length=None)
    if template:
        return success_response(payload={"result": template})
    return success_response(payload={"success": False, "result": {}}, message="Success")


@router.get("/app-configuration")
async def generate_config(
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    app_config = await db["app_config"].find_one({"type": "menu", "id": 1})
    if app_config:
        return success_response(payload={"result": {"config": app_config.get("config")}})
    return success_response(payload={"success": False, "result": []}, message="Success")


@router.get("/getNotification")
async def get_notification(
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    return success_response(
        payload={
            "results": [
                {"id": 1, "info": "You have a new message", "aName": "Alice"},
                {"id": 2, "info": "Class starts at 6 PM", "aName": "Gym"},
            ]
        }
    )


@router.get("/getDataBaseStatisics")
async def get_database_statistics(
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    result = await db.command("dbStats", scale=1024)
    if result:
        return success_response(payload={"result": result})
    return success_response(payload={"success": False, "result": {}}, message="Success")


@router.post("/upload")
async def upload_file(
    files: list[UploadFile] = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    if not files:
        raise ApiError(400, "No files uploaded.")

    storage_directory = settings.STORAGE_ROOT / request_context.app_name
    storage_directory.mkdir(parents=True, exist_ok=True)

    file_details = []
    for upload in files[:10]:
        file_name = _create_upload_name(upload.filename)
        destination = storage_directory / file_name
        content = await upload.read()
        destination.write_bytes(content)

        file_details.append(
            {
                "filename": file_name,
                "originalName": upload.filename,
                "size": len(content),
                "mimeType": upload.content_type,
                "absolutePath": str(destination),
                "accessObjectPath": f"public/storage/{request_context.app_name}/{file_name}",
                "accessUrl": f"{settings.FILE_UPLOAD_URL.rstrip('/')}/{request_context.app_name}/{file_name}",
            }
        )

    await db["uploadFiles"].insert_one(
        {
            "uploadFiles": file_details,
            "appName": request_context.app_name,
            **current_user,
        }
    )

    return success_response(
        payload={"uploadFiles": file_details},
        message="Files uploaded successfully:",
    )
