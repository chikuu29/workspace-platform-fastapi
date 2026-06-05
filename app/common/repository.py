# from typing import Any, Dict, List, Optional
# from motor.motor_asyncio import AsyncIOMotorDatabase
# from bson import ObjectId
# from app.core.logger import create_logger

# class BaseRepository:
#     """
#     Generic Base Repository to handle standard CRUD operations for MongoDB.
#     Dynamically accesses collections to support Multi-Tenancy inherently securely.
#     """
#     def __init__(self, db: AsyncIOMotorDatabase, collection_name: str):
#         self.db = db
#         self.collection_name = collection_name
#         self.logger = create_logger("database")

#     @property
#     def collection(self):
#         """Returns the collection dynamically bound to current Tenant context."""
#         return self.db[self.collection_name]

#     async def get_by_id(self, id: str) -> Optional[Dict[str, Any]]:
#         """Fetch a document by its ObjectId."""
#         self.logger.debug(f"Fetching document by ID={id} from collection={self.collection_name}")
#         document = await self.collection.find_one({"_id": ObjectId(id)})
#         if document:
#             document["_id"] = str(document["_id"])
#         return document

#     async def create(self, document: Dict[str, Any]) -> str:
#         """Insert a new document and return its string ID."""
#         self.logger.info(f"Creating new document in collection={self.collection_name}")
#         result = await self.collection.insert_one(document)
#         return str(result.inserted_id)

#     async def find(self, query: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
#         """Find multiple documents matching a query."""
#         self.logger.debug(f"Querying collection={self.collection_name} with limit={limit}")
#         cursor = self.collection.find(query).limit(limit)
#         documents = []
#         async for doc in cursor:
#             doc["_id"] = str(doc["_id"])
#             documents.append(doc)
#         return documents

#     async def update(self, id: str, update_data: Dict[str, Any]) -> bool:
#         """Update a document by its ObjectId."""
#         self.logger.info(f"Updating document ID={id} in collection={self.collection_name}")
#         result = await self.collection.update_one(
#             {"_id": ObjectId(id)}, {"$set": update_data}
#         )
#         return result.modified_count > 0

#     async def delete(self, id: str) -> bool:
#         """Delete a document by its ObjectId."""
#         self.logger.warning(f"Deleting document ID={id} from collection={self.collection_name}")
#         result = await self.collection.delete_one({"_id": ObjectId(id)})
#         return result.deleted_count > 0
