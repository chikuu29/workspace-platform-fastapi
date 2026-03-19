from fastapi import APIRouter, Depends, status
from app.api.dependencies import get_current_user
from app.modules.users.schemas import UserCreate, UserInDB
from app.modules.users.service import UserService
from app.modules.users.dependencies import get_user_service

router = APIRouter()

@router.post("/", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate, 
    service: UserService = Depends(get_user_service)
):
    return await service.create_user(user_in)

@router.get("/me", response_model=UserInDB)
async def read_user_me(
    current_user: dict = Depends(get_current_user)
):
    # Depending on how authentication unpacks the user, `_id` might be present
    if "_id" in current_user:
        current_user["id"] = str(current_user.pop("_id"))
    elif "id" not in current_user and "email" in current_user: # Mocked or JWT unpacked mock
        current_user["id"] = "unknown"
        
    return current_user
