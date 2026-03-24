from fastapi import APIRouter, Depends, Request, HTTPException, Query
from datetime import datetime
from typing import Optional
from app.core.security.authentications import get_authenticated_identity
from app.db.database import get_database
from app.db.sequence import generate_monthly_sequence, generate_simple_sequence
from bson import ObjectId

router = APIRouter(
    dependencies=[Depends(get_authenticated_identity)]
)

# Helper to format MongoDB document for JSON response
def serialize_doc(doc):
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

@router.post("/addMember")
async def add_member(request: Request):
    print("Received request to add member",request.state.__dict__)  # Debug: Check security headers from middleware

    db = get_database()
    # 1. Extract contextual data from Request/Payload
    payload = await request.json()
    print("Payload received:", payload)
    # In a real app, org_id comes from JWT token, here we simulate getting it from payload headers or body
    org_id = payload.get("org_id", "default_org") 
    app_id = payload.get("app_id", "myGym")
    
    # Generate Next Sequence for the generic record (e.g., GYM-202603-0001)
    new_record_id = await generate_monthly_sequence(org_id, app_id, "addMember", prefix="GYM")
    
    # Generate a unique member_id specifically for the member entity via continuous sequence (e.g., M-1)
    new_member_id = await generate_simple_sequence(org_id, app_id, "member", prefix="M")
    payload["member_id"] = new_member_id
    
    # Create the generic platform record
    record = {
        "org_id": org_id,
        "app_id": app_id,
        "form_id": "addMember",
        "record_id": new_record_id,
        "data": payload,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    # Save to central collection
    result = await db.data_records.insert_one(record)
    
    return {
        "message": "Membership registration successful!",
        "result": {
            "record_id": new_record_id,
            "member_id": new_member_id,
            "status": "Active",
            "_id": str(result.inserted_id)
        },
        "success": True
    }

@router.get("/members")
async def get_members(
    org_id: str = "default_org", 
    app_id: str = "myGym", 
    skip: int = Query(0, ge=0), 
    limit: int = Query(50, le=100)
):
    db = get_database()
    
    query = {
        "org_id": org_id,
        "app_id": app_id,
        "form_id": "addMember"
    }
    
    cursor = db.data_records.find(query).sort("created_at", -1).skip(skip).limit(limit)
    documents = await cursor.to_list(length=limit)
    
    total_count = await db.data_records.count_documents(query)
    
    return {
        "success": True,
        "data": [serialize_doc(doc) for doc in documents],
        "total": total_count,
        "skip": skip,
        "limit": limit
    }

@router.get("/members/{identifier}")
async def get_member(identifier: str):
    db = get_database()
    
    # Retrieve flexibly based on generated sequence id, member_id, OR object Id
    query = {
        "$or": [
            {"record_id": identifier},
            {"data.member_id": identifier}
        ]
    }
    
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
            
    doc = await db.data_records.find_one(query)
            
    if not doc:
        raise HTTPException(status_code=404, detail="Member or Record not found")
        
    return {
        "success": True,
        "data": serialize_doc(doc)
    }

@router.put("/members/{identifier}")
async def update_member(identifier: str, request: Request):
    db = get_database()
    update_data = await request.json()
    
    # Remove immutable fields if present in update
    update_data.pop("_id", None)
    update_data.pop("record_id", None)
    update_data.pop("org_id", None)
    update_data.pop("app_id", None)
    # Don't let them overwrite member_id either
    update_data.pop("member_id", None) 
    
    query = {
        "$or": [
            {"record_id": identifier},
            {"data.member_id": identifier}
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})

    # We update the 'data' field, recording the new body
    update_payload = {
        "$set": {
            "data": update_data,
            "updated_at": datetime.utcnow()
        }
    }
    
    result = await db.data_records.find_one_and_update(
        query,
        update_payload,
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Member or Record not found")
        
    return {
        "success": True,
        "message": "Record updated successfully",
        "data": serialize_doc(result)
    }

@router.delete("/members/{identifier}")
async def delete_member(identifier: str):
    db = get_database()
    
    query = {
        "$or": [
            {"record_id": identifier},
            {"data.member_id": identifier}
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
        
    result = await db.data_records.delete_one(query)
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Member or Record not found")
        
    return {
        "success": True,
        "message": "Record deleted successfully"
    }
