
from app.modules.users.repository import UserRepository

from app.core.logger import create_logger

class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository
        self.logger = create_logger("user_service")

    