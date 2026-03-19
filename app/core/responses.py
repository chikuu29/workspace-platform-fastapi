from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

try:
    from bson import ObjectId
except ImportError:  # pragma: no cover
    ObjectId = None


def success_payload(
    payload: Optional[Dict[str, Any]] = None,
    message: str = "Success",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "success": True,
        "message": message,
    }
    if payload:
        body.update(payload)
    return body


def error_payload(
    message: str = "Something went wrong",
    errors: Optional[Any] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "success": False,
        "message": message,
    }
    if errors is not None:
        body["errors"] = errors
    if payload:
        body.update(payload)
    return body


def success_response(
    payload: Optional[Dict[str, Any]] = None,
    message: str = "Success",
    status_code: int = 200,
) -> JSONResponse:
    custom_encoder = {ObjectId: str} if ObjectId is not None else None
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            success_payload(payload=payload, message=message),
            custom_encoder=custom_encoder,
        ),
    )
