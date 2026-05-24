from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.org_repository import OrgRepository
from app.core.context import OrgContext
from app.core.logger import create_logger
from app.modules.hostel.entities.common import HostelEntity

repository_logger = create_logger("hostel.repository")


class HostelEntityRepository(OrgRepository):
    entity: HostelEntity

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, "records", ctx)

    @property
    def entity_query(self) -> Dict[str, Any]:
        return self.entity.query

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        repository_logger.info(
            "Creating hostel entity=%s org=%s user=%s",
            self.entity.entity_type,
            self._ctx.org_id,
            self._ctx.user_id,
        )
        return await self.insert_one(
            data=data,
            entity_type=self.entity.entity_type,
            prefix=self.entity.prefix,
        )

    async def list(
        self,
        *,
        sort: Optional[List] = None,
        skip: int = 0,
        limit: int = 50,
        query: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return await self.find(
            {**self.entity_query, **(query or {})},
            sort=sort,
            skip=skip,
            limit=limit,
        )

    async def total(self, query: Optional[Dict[str, Any]] = None) -> int:
        return await self.count({**self.entity_query, **(query or {})})

    async def find_entity(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await self.find_one({**self.entity_query, **query})

    async def update_entity(
        self,
        query: Dict[str, Any],
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return await self.update_one({**self.entity_query, **query}, data)

