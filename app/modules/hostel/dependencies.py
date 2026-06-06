from __future__ import annotations

from fastapi import Depends

from app.core.context import OrgContext, get_org_context
from app.core.database import get_db
from app.modules.hostel.repositories import HostelRepositories
from app.modules.hostel.services import HostelService


def get_hostel_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
) -> HostelService:
    return HostelService(
        repositories=HostelRepositories(db, ctx),
        db=db,
        ctx=ctx,
    )

