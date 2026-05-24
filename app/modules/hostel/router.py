from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import created, ok, paginated
from app.core.logger import create_logger
from app.core.security.authentications import get_authenticated_identity
from app.modules.hostel.dependencies import get_hostel_service
from app.modules.hostel.schemas import sanitize_payload
from app.modules.hostel.services import HostelService

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])
logger = create_logger("hostel.router")


@router.get("/analytics/kpis")
async def get_hostel_kpis(
    service: HostelService = Depends(get_hostel_service),
):
    logger.info("Hostel KPI request")
    return ok(
        message="Hostel KPIs successfully aggregated.",
        data=await service.kpis(),
    )


@router.post("/addBuilding")
async def add_building(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.add_building(data)
    return created(message="Hostel building added successfully.", data=document)


@router.get("/buildings")
async def get_buildings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    result = await service.list_buildings(skip=skip, limit=limit)
    return paginated(
        message="Hostel buildings retrieved.",
        data=result["documents"],
        total=result["total"],
        skip=skip,
        limit=limit,
    )


@router.get("/buildings/options")
async def get_buildings_options(
    service: HostelService = Depends(get_hostel_service),
):
    return ok(
        message="Building options retrieved successfully.",
        data=await service.building_options(),
    )


@router.post("/addRoom")
async def add_room(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.add_room(data)
    return created(message="Hostel room added successfully.", data=document)


@router.get("/rooms/options")
async def get_rooms_options(
    buildingName: Optional[str] = Query(None),
    service: HostelService = Depends(get_hostel_service),
):
    return ok(
        message="Available room options retrieved successfully.",
        data=await service.room_options(buildingName),
    )


@router.get("/rooms/security-deposit")
async def get_room_security_deposit(
    buildingName: str = Query(...),
    roomNumber: str = Query(...),
    service: HostelService = Depends(get_hostel_service),
):
    return ok(
        message="Security deposit calculated successfully.",
        data=await service.room_security_deposit(buildingName, roomNumber),
    )


@router.get("/rooms")
async def get_rooms(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    result = await service.list_rooms(skip=skip, limit=limit)
    return paginated(
        message="Hostel rooms retrieved.",
        data=result["documents"],
        total=result["total"],
        skip=skip,
        limit=limit,
    )


@router.post("/addGuest")
async def add_guest(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.add_guest(data)
    return created(message="Guest onboarded and allocated successfully.", data=document)


@router.get("/guests")
async def get_guests(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    result = await service.list_guests(skip=skip, limit=limit)
    return paginated(
        message="Guests retrieved successfully.",
        data=result["documents"],
        total=result["total"],
        skip=skip,
        limit=limit,
    )


@router.get("/tenants")
async def get_tenants_legacy(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    return await get_guests(skip=skip, limit=limit, service=service)


@router.post("/billing/invoice")
async def generate_invoice(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.generate_invoice(data)
    return created(message="Guest invoice generated successfully.", data=document)


@router.post("/billing/pay")
async def record_payment(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.record_payment(data)
    return ok(message="Payment processed and invoice updated.", data=document)


@router.get("/billing")
async def get_billing(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    result = await service.list_billing(skip=skip, limit=limit)
    return paginated(
        message="Invoices successfully retrieved.",
        data=result["documents"],
        total=result["total"],
        skip=skip,
        limit=limit,
    )


@router.post("/complaints")
async def create_complaint(
    request: Request,
    service: HostelService = Depends(get_hostel_service),
):
    data = sanitize_payload(await request.json())
    document = await service.create_complaint(data)
    return created(message="Complaint logged successfully.", data=document)


@router.get("/complaints")
async def get_complaints(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: HostelService = Depends(get_hostel_service),
):
    result = await service.list_complaints(skip=skip, limit=limit)
    return paginated(
        message="Complaints retrieved.",
        data=result["documents"],
        total=result["total"],
        skip=skip,
        limit=limit,
    )

