from datetime import datetime
from app.db.database import get_database
from motor.motor_asyncio import AsyncIOMotorDatabase

async def generate_monthly_sequence(org_id: str, app_id: str, form_id: str, prefix: str = "MEM") -> str:
    """
    Atomically increments a sequence for a specific organization + app + form within the current month.
    Generates an ID in the format: PREFIX-YYYYMM-0001
    """
    db: AsyncIOMotorDatabase = get_database()
    
    # Get current YYYYMM (e.g. '202603')
    current_month = datetime.utcnow().strftime("%Y%m")
    
    # Unique ID representing this exact "bucket"
    counter_id = f"{org_id}:{app_id}:{form_id}:{current_month}"
    
    # Atomically increment the sequence counter using MongoDB
    sequence_doc = await db.sequences.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    
    seq_number = sequence_doc["seq"]
    
    # Format: PREFIX-202603-0001
    return f"{prefix}-{current_month}-{seq_number:04d}"

async def generate_simple_sequence(org_id: str, app_id: str, entity_type: str, prefix: str) -> str:
    """
    Atomically increments a simple continuous sequence for an entity.
    Generates an ID in the format: PREFIX-1, PREFIX-2
    """
    db: AsyncIOMotorDatabase = get_database()
    
    counter_id = f"{org_id}:{app_id}:{entity_type}:continuous"
    
    sequence_doc = await db.sequences.find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    
    seq_number = sequence_doc["seq"]
    
    return f"{prefix}-{seq_number}"
