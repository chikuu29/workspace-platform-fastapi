from typing import Dict, Any
from app.core.security import get_password_hash
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from fastapi import HTTPException
from app.core.logger import create_logger

class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository
        self.logger = create_logger("user_service")

    async def create_user(self, user_in: UserCreate) -> Dict[str, Any]:
        self.logger.info(f"Attempting to create generic user: {user_in.email}")
        existing_user = await self.repository.get_by_email(user_in.email)
        if existing_user:
            self.logger.warning(f"Registration failed: User {user_in.email} already exists")
            raise HTTPException(
                status_code=400,
                detail="The user with this username already exists in the system.",
            )
        
        user_dict = user_in.model_dump()
        user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))
        
        self.logger.debug("Hashing completed, delegating to repository")
        created_user = await self.repository.create_user(user_dict)
        self.logger.info(f"Successfully created generic user ID={created_user.get('id')}")
        return created_user
