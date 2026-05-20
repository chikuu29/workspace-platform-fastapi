"""
Hostel Module Router — Isolated multi-tenant operations for room management,
tenant boarding, utility bill splits, invoicing, and complaint tickets.

All endpoints utilize OrgContext for secure multi-tenant data isolation.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from bson import ObjectId

from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, paginated, deleted, not_found, bad_request, conflict
from app.db.database import get_database
from app.db.org_sequence import OrgSequenceService
from app.modules.hostel.schemas import sanitize_payload

router = APIRouter(
    dependencies=[Depends(get_authenticated_identity)]
)

# ── Entity Constants ─────────────────────────────────────────────────
ENTITY_BUILDING = "hostel_building"
ENTITY_ROOM = "hostel_room"
ENTITY_TENANT = "hostel_tenant"
ENTITY_INVOICE = "hostel_invoice"
ENTITY_COMPLAINT = "hostel_complaint"

# ── Base Filters ─────────────────────────────────────────────────────
BUILDING_QUERY = {"_meta.entity_type": ENTITY_BUILDING}
ROOM_QUERY = {"_meta.entity_type": ENTITY_ROOM}
TENANT_QUERY = {"_meta.entity_type": ENTITY_TENANT}
INVOICE_QUERY = {"_meta.entity_type": ENTITY_INVOICE}
COMPLAINT_QUERY = {"_meta.entity_type": ENTITY_COMPLAINT}


def _record_query(identifier: str) -> dict:
    """Build a flexible lookup query by record_id, or ObjectId."""
    query = {
        "$or": [
            {"_meta.record_id": identifier},
            {"data.tenant_id": identifier},
            {"data.room_number": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD STATS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/kpis")
async def get_hostel_kpis(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Aggregate hostel dashboard KPIs in a single backend call.
    Computes room occupancy, active tenants count, outstanding dues, and open complaints.
    """
    repo = OrgRepository(db, "records", ctx)

    # 1. Rooms and Occupancy Aggregation
    rooms = await repo.find(ROOM_QUERY)
    total_beds = 0
    occupied_beds = 0
    for room in rooms:
        capacity = int(room["data"].get("capacity") or 1)
        occupants = len(room["data"].get("occupants") or [])
        total_beds += capacity
        occupied_beds += occupants

    occupancy_rate = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0.0

    # 2. Counts
    total_tenants = await repo.count(TENANT_QUERY)
    open_complaints = await repo.count({**COMPLAINT_QUERY, "data.status": {"$ne": "Resolved"}})

    # 3. Dues calculation: Sum of unpaid/partially paid invoices
    unpaid_pipeline = [
        {"$match": {**ctx.active_filter, **INVOICE_QUERY, "data.status": {"$in": ["Unpaid", "Partially Paid"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$data.amount_due"}}}
    ]
    unpaid_cursor = repo.collection.aggregate(unpaid_pipeline)
    unpaid_result = await unpaid_cursor.to_list(length=1)
    total_dues = unpaid_result[0]["total"] if unpaid_result else 0.0

    # 4. Recent tenants list
    recent_docs = await repo.find(
        TENANT_QUERY,
        sort=[("_meta.created.at", -1)],
        limit=5,
    )
    recent_tenants = [
        {
            "record_id": d["_meta"]["record_id"],
            "name": f"{d['data'].get('firstName', '')} {d['data'].get('lastName', '')}".strip(),
            "room_number": d["data"].get("room_number", "N/A"),
            "created_at": d["_meta"]["created"]["at"],
        }
        for d in recent_docs
    ]

    return ok(
        message="Hostel KPIs successfully aggregated.",
        data={
            "kpis": {
                "total_beds": total_beds,
                "occupied_beds": occupied_beds,
                "occupancy_rate": f"{occupancy_rate}%",
                "active_tenants": total_tenants,
                "total_dues": total_dues,
                "open_complaints": open_complaints,
            },
            "recent_tenants": recent_tenants,
        }
    )


# ══════════════════════════════════════════════════════════════════════
#  BUILDING CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/addBuilding")
async def add_building(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Add a new hostel building/block at a specific location.
    Ensures building names are unique within the organization.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    if not data.get("name"):
        bad_request(message="name is required.")

    repo = OrgRepository(db, "records", ctx)

    # Prevent duplicate building names within this organization
    existing = await repo.find_one({
        **BUILDING_QUERY,
        "data.name": data["name"]
    })
    if existing:
        conflict(
            message=f"Building '{data['name']}' already exists.",
            error_code="DUPLICATE_BUILDING",
        )

    document = await repo.insert_one(
        data=data,
        entity_type=ENTITY_BUILDING,
        prefix="BUILD",
    )

    return created(
        message="Hostel building added successfully.",
        data=document,
    )


@router.get("/buildings")
async def get_buildings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """List isolated buildings scoped by tenant organization."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        BUILDING_QUERY,
        sort=[("data.name", 1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(BUILDING_QUERY)

    return paginated(
        message="Hostel buildings retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/buildings/options")
async def get_buildings_options(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Get flat building options for SelectField dropdowns."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        BUILDING_QUERY,
        sort=[("data.name", 1)],
    )

    options = []
    for doc in documents:
        name = doc["data"].get("name", "Unnamed Building")
        loc = doc["data"].get("location", "")
        label = f"{name} ({loc})" if loc else name
        options.append({
            "id": name,  # Submitted field value matches current room scheme
            "name": label
        })

    return ok(
        message="Building options retrieved successfully.",
        data=options,
    )


# ══════════════════════════════════════════════════════════════════════
#  ROOM CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/addRoom")
async def add_room(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Add a new hostel room.
    Ensures the room number is unique within the organization scope.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    if not data.get("roomNumber"):
        bad_request(message="roomNumber is required.")

    repo = OrgRepository(db, "records", ctx)

    # Prevent duplicate room numbers within this organization
    existing = await repo.find_one({
        **ROOM_QUERY,
        "data.roomNumber": data["roomNumber"]
    })
    if existing:
        conflict(
            message=f"Room '{data['roomNumber']}' already exists.",
            error_code="DUPLICATE_ROOM",
        )

    # Initialize roommates occupants list
    data.setdefault("occupants", [])
    data.setdefault("capacity", 2)
    data.setdefault("status", "Empty")
    data.setdefault("rentAmount", 5000)

    document = await repo.insert_one(
        data=data,
        entity_type=ENTITY_ROOM,
        prefix="ROOM",
    )

    return created(
        message="Hostel room added successfully.",
        data=document,
    )


@router.get("/rooms")
async def get_rooms(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """List isolated rooms scoped by tenant organization."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        ROOM_QUERY,
        sort=[("data.roomNumber", 1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(ROOM_QUERY)

    # Dynamically compute occupancy status
    for doc in documents:
        cap = int(doc["data"].get("capacity") or 2)
        count = len(doc["data"].get("occupants") or [])
        if count == 0:
            doc["data"]["status"] = "Empty"
        elif count >= cap:
            doc["data"]["status"] = "Fully Occupied"
        else:
            doc["data"]["status"] = "Partially Occupied"

    return paginated(
        message="Hostel rooms retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


# ══════════════════════════════════════════════════════════════════════
#  TENANT CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/addTenant")
async def add_tenant(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Board a new tenant and allocate them to a room if specified.
    Increments occupants list inside room configuration.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    if not data.get("firstName") or not data.get("lastName"):
        bad_request(message="firstName and lastName are required.")

    repo = OrgRepository(db, "records", ctx)
    room_num = data.get("room_number")

    # 1. If room selected, check room availability and capacity
    room_doc = None
    if room_num:
        room_doc = await repo.find_one({
            **ROOM_QUERY,
            "data.roomNumber": room_num
        })
        if not room_doc:
            not_found(message=f"Room '{room_num}' not found.")

        capacity = int(room_doc["data"].get("capacity") or 2)
        current_occupants = list(room_doc["data"].get("occupants") or [])
        if len(current_occupants) >= capacity:
            bad_request(
                message=f"Room '{room_num}' is already fully occupied.",
                error_code="ROOM_FULL",
            )

    # 2. Sequence generated Tenant ID
    seq = OrgSequenceService(db, ctx)
    tenant_id = await seq.simple("tenant", prefix="T")
    data["tenant_id"] = tenant_id
    data.setdefault("status", "Active")
    data.setdefault("rent_status", "Paid")

    # 3. Create Tenant
    tenant_doc = await repo.insert_one(
        data=data,
        entity_type=ENTITY_TENANT,
        prefix="TNT",
    )

    # 4. Add occupant to Room list in MongoDB records
    if room_doc:
        occupants_list = list(room_doc["data"].get("occupants") or [])
        occupants_list.append({
            "tenant_id": tenant_id,
            "name": f"{data['firstName']} {data['lastName']}".strip(),
            "phone": data.get("phone", "")
        })

        room_update = {"occupants": occupants_list}
        # Update dynamic status based on occupancy
        capacity = int(room_doc["data"].get("capacity") or 2)
        if len(occupants_list) >= capacity:
            room_update["status"] = "Fully Occupied"
        else:
            room_update["status"] = "Partially Occupied"

        await repo.update_one(
            {**ROOM_QUERY, "data.roomNumber": room_num},
            room_update
        )

    return created(
        message="Tenant onboarded and allocated successfully.",
        data=tenant_doc,
    )


@router.get("/tenants")
async def get_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Retrieve isolated list of tenants."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        TENANT_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(TENANT_QUERY)

    # Dynamically verify if they have pending dues to update rent_status
    for doc in documents:
        tenant_id = doc["data"].get("tenant_id")
        unpaid = await repo.count({
            **INVOICE_QUERY,
            "data.tenant_id": tenant_id,
            "data.status": {"$in": ["Unpaid", "Partially Paid"]}
        })
        doc["data"]["rent_status"] = "Overdue" if unpaid > 0 else "Paid"

    return paginated(
        message="Tenants retrieved successfully.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


# ══════════════════════════════════════════════════════════════════════
#  BILLING & UTILITY BILL SPLITTING
# ══════════════════════════════════════════════════════════════════════

@router.post("/billing/invoice")
async def generate_invoice(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Generate an invoice for a tenant.
    Supports dynamic split-billing for utility metrics among all occupants currently allocated to a room.

    Expected payload:
    {
        "tenant_id": "T-1",
        "description": "May Rent + Utilities",
        "is_utility_split": true,
        "utility_total_amount": 3000.0,   # Total utility bill (water/electricity) for the entire room
        "utility_type": "Electricity"
    }
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    tenant_id = data.get("tenant_id")
    if not tenant_id:
        bad_request(message="tenant_id is required.")

    repo = OrgRepository(db, "records", ctx)

    # 1. Load tenant information
    tenant_doc = await repo.find_one({
        **TENANT_QUERY,
        "data.tenant_id": tenant_id
    })
    if not tenant_doc:
        not_found(message=f"Tenant '{tenant_id}' not found.")

    tenant_name = f"{tenant_doc['data'].get('firstName', '')} {tenant_doc['data'].get('lastName', '')}".strip()
    room_number = tenant_doc["data"].get("room_number")

    if not room_number:
        bad_request(message=f"Tenant '{tenant_id}' is not currently allocated to any room.")

    # 2. Get Room details for rent amount & occupants list
    room_doc = await repo.find_one({
        **ROOM_QUERY,
        "data.roomNumber": room_number
    })
    if not room_doc:
        not_found(message=f"Allocated Room '{room_number}' not found.")

    base_rent = float(room_doc["data"].get("rentAmount") or 5000.0)

    # 3. Dynamic Utility Bill Splitting among current room roommates
    utility_split_charge = 0.0
    utility_log_notes = ""

    if data.get("is_utility_split") and data.get("utility_total_amount"):
        roommates = list(room_doc["data"].get("occupants") or [])
        roommates_count = len(roommates)
        if roommates_count > 0:
            total_bill = float(data["utility_total_amount"])
            utility_split_charge = round(total_bill / roommates_count, 2)
            utility_log_notes = (
                f"Split billing for {data.get('utility_type', 'Utilities')}: "
                f"Total Room Bill {total_bill} divided by {roommates_count} roommates = {utility_split_charge} each."
            )
        else:
            utility_split_charge = float(data["utility_total_amount"])
            utility_log_notes = "Room is occupied solely by this tenant. Full utility charge applied."

    total_invoice_amount = base_rent + utility_split_charge

    # 4. Generate unique Invoice ID sequence
    seq = OrgSequenceService(db, ctx)
    invoice_id = await seq.simple("invoice", prefix="INV")

    invoice_data = {
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "room_number": room_number,
        "base_rent": base_rent,
        "utility_charge": utility_split_charge,
        "utility_notes": utility_log_notes,
        "amount_due": total_invoice_amount,
        "amount_paid": 0.0,
        "status": "Unpaid",
        "description": data.get("description", "Monthly Rent Invoice"),
        "billing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    invoice_doc = await repo.insert_one(
        data=invoice_data,
        entity_type=ENTITY_INVOICE,
        prefix="INV",
    )

    return created(
        message="Tenant invoice generated successfully.",
        data=invoice_doc,
    )


@router.post("/billing/pay")
async def record_payment(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Record payment against a specific invoice.
    Updates unpaid balance and updates status to Paid or Partially Paid.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    invoice_id = data.get("invoice_id")
    payment_amount = float(data.get("amount", 0.0))

    if not invoice_id:
        bad_request(message="invoice_id is required.")
    if payment_amount <= 0.0:
        bad_request(message="Payment amount must be greater than zero.")

    repo = OrgRepository(db, "records", ctx)

    # 1. Fetch invoice document
    invoice_doc = await repo.find_one({
        **INVOICE_QUERY,
        "data.invoice_id": invoice_id
    })
    if not invoice_doc:
        not_found(message=f"Invoice '{invoice_id}' not found.")

    current_due = float(invoice_doc["data"].get("amount_due") or 0.0)
    current_paid = float(invoice_doc["data"].get("amount_paid") or 0.0)

    if current_due <= 0.0:
        bad_request(message="This invoice has already been fully paid.")

    new_paid = current_paid + payment_amount
    new_due = max(0.0, current_due - payment_amount)
    status_state = "Paid" if new_due == 0.0 else "Partially Paid"

    update_payload = {
        "amount_due": new_due,
        "amount_paid": new_paid,
        "status": status_state,
        "payment_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "payment_method": data.get("payment_method", "Cash")
    }

    updated_doc = await repo.update_one(
        {**INVOICE_QUERY, "data.invoice_id": invoice_id},
        update_payload
    )

    return ok(
        message="Payment processed and invoice updated.",
        data=updated_doc
    )


@router.get("/billing")
async def get_billing(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Retrieve list of invoices for the organization."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        INVOICE_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(INVOICE_QUERY)

    return paginated(
        message="Invoices successfully retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


# ══════════════════════════════════════════════════════════════════════
#  MAINTENANCE & COMPLAINTS CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/complaints")
async def create_complaint(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Submit a new complaint ticket."""
    raw = await request.json()
    data = sanitize_payload(raw)

    if not data.get("description") or not data.get("category"):
        bad_request(message="category and description are required.")

    repo = OrgRepository(db, "records", ctx)

    seq = OrgSequenceService(db, ctx)
    ticket_id = await seq.simple("complaint", prefix="TKT")
    data["ticket_id"] = ticket_id
    data.setdefault("status", "Pending")
    data.setdefault("urgency", "Medium")

    complaint_doc = await repo.insert_one(
        data=data,
        entity_type=ENTITY_COMPLAINT,
        prefix="TKT",
    )

    return created(
        message="Complaint logged successfully.",
        data=complaint_doc,
    )


@router.get("/complaints")
async def get_complaints(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """List complaint tickets with multi-tenant isolation filters."""
    repo = OrgRepository(db, "records", ctx)
    documents = await repo.find(
        COMPLAINT_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(COMPLAINT_QUERY)

    return paginated(
        message="Complaints retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )
