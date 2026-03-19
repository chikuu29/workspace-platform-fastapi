from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.core.logger import create_logger

logger = create_logger("database")

class Database:
    client: AsyncIOMotorClient = None
    db = None

db = Database()

async def connect_to_mongo():
    db.client = AsyncIOMotorClient(settings.MONGO_URI)
    db.db = db.client[settings.DATABASE_NAME]
    logger.info("Connected to MongoDB")

async def close_mongo_connection():
    if db.client:
        db.client.close()
        logger.info("Closed MongoDB connection")

def get_database():
    return db.db
