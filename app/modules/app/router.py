from typing import Any
from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.dependencies import RequestContext, get_current_user, require_request_context
from app.core.errors import ApiError
from app.core.responses import success_response

from app.modules.app.service import AppService
from app.modules.app.dependencies import get_app_service

router = APIRouter()

@router.get("/ui_template")
async def get_template(
    request: Request,
    service: AppService = Depends(get_app_service),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    query = dict(request.query_params)
    template = await service.get_templates(query)
    if template:
        return success_response(payload={"result": template})
    return success_response(payload={"success": False, "result": {}}, message="Success")


@router.get("/app-configuration")
async def generate_config(
    service: AppService = Depends(get_app_service),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    config = await service.get_app_configuration()
    if config:
        return success_response(payload={"result": {"config": config}})
    return success_response(payload={"success": False, "result": []}, message="Success")


@router.get("/getNotification")
async def get_notification(
    service: AppService = Depends(get_app_service),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    return success_response(payload={"results": service.get_notifications()})


@router.get("/getDataBaseStatisics")
async def get_database_statistics(
    service: AppService = Depends(get_app_service),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    del request_context, current_user
    result = await service.get_database_statistics()
    if result:
        return success_response(payload={"result": result})
    return success_response(payload={"success": False, "result": {}}, message="Success")


@router.post("/upload")
async def upload_file(
    files: list[UploadFile] = File(...),
    service: AppService = Depends(get_app_service),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    if not files:
        raise ApiError(400, "No files uploaded.")

    file_details = await service.upload_files(
        files=files, 
        app_name=request_context.app_name, 
        current_user=current_user
    )

    return success_response(
        payload={"uploadFiles": file_details},
        message="Files uploaded successfully:",
    )
