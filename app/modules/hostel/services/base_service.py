from __future__ import annotations

from app.core.context import OrgContext
from app.core.logger import create_logger
from app.db.org_sequence import OrgSequenceService
from app.modules.hostel.repositories.hostel_repository import HostelRepositories

service_logger = create_logger("hostel.service")


class BaseHostelService:
    def __init__(
        self,
        repositories: HostelRepositories,
        db,
        ctx: OrgContext,
    ) -> None:
        self.repositories = repositories
        self.db = db
        self.ctx = ctx

    @property
    def sequence(self) -> OrgSequenceService:
        return OrgSequenceService(self.db, self.ctx)

