from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from app.db.database import get_database
from app.api.dependencies import get_current_user
from app.modules.users.schemas import UserCreate, UserInDB
from app.core.security import get_password_hash

router = APIRouter()

@router.post("/", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate, 
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    existing_user = await db["users"].find_one({"email": user_in.email})
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    
    user_dict = user_in.model_dump()
    user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))
    
    result = await db["users"].insert_one(user_dict)
    
    created_user = await db["users"].find_one({"_id": result.inserted_id})
    created_user["id"] = str(created_user.pop("_id"))
    
    return created_user

@router.get("/me", response_model=UserInDB)
async def read_user_me(
    current_user: dict = Depends(get_current_user)
):
    current_user["id"] = str(current_user.pop("_id"))
    return current_user
