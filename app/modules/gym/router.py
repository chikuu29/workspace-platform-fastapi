from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies import RequestContext, get_current_user, require_request_context
from app.core.responses import success_response
from app.db.database import get_database

router = APIRouter()


@router.post("/addMember")
async def add_member(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context: RequestContext = Depends(require_request_context),
    current_user: dict = Depends(get_current_user),
):
    document = {
        "recentData": payload,
        "appName": request_context.app_db_collection or request_context.app_name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "createdByEmail": current_user.get("email"),
        "clientDetails": current_user,
    }
    collection_name = request_context.app_db_collection or "gym"
    result = await db[collection_name].insert_one(document)

    return success_response(
        payload={
            "result": {
                "inserted_id": str(result.inserted_id),
                "data": document,
            }
        },
        message="Member added successfully",
    )
