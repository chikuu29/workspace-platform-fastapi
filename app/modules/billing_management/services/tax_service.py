"""
Tax Service — tax profile management and tax computation API.

Wraps the pure TaxEngine with database operations for GSTIN
profile CRUD and provides a convenience compute endpoint.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, conflict, not_found
from app.core.context import OrgContext
from app.core.logger import create_logger
from app.modules.billing_management.constants import ENTITY_TAX_PROFILE
from app.modules.billing_management.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
)
from app.modules.billing_management.repositories.billing_repos import (
    TaxProfileRepository,
)

logger = create_logger("billing.tax_service")


class TaxService:
    """Tax profile management and GST computation."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx
        self._repo = TaxProfileRepository(db, ctx)

    async def create_profile(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new tax profile (GSTIN registration)."""
        gstin = data.get("gstin", "").strip()
        if not gstin:
            bad_request(message="GSTIN is required.")

        # Duplicate GSTIN check
        existing = await self._repo.find_by_gstin(gstin)
        if existing:
            conflict(
                message=f"A tax profile with GSTIN '{gstin}' already exists.",
                error_code="DUPLICATE_GSTIN",
            )

        # If this is set as default, unset any existing default
        if data.get("is_default"):
            current_default = await self._repo.find_default()
            if current_default:
                await self._repo.update_one(
                    {"data.gstin": current_default["data"]["gstin"]},
                    {"is_default": False},
                )

        data.setdefault("tax_type", "gst")
        data.setdefault("default_tax_category", "higher")
        data.setdefault("is_composition_scheme", False)

        document = await self._repo.insert_one(
            data=data,
            entity_type=ENTITY_TAX_PROFILE,
            prefix="TAX",
        )
        logger.info("Created tax profile gstin=%s org=%s", gstin, self._ctx.org_id)
        return document

    async def list_profiles(
        self, *, skip: int = 0, limit: int = 50,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List all tax profiles for the org."""
        documents = await self._repo.find(
            {},
            sort=[("data.is_default", -1), ("data.profile_name", 1)],
            skip=skip,
            limit=limit,
        )
        total = await self._repo.count({})
        return documents, total

    async def get_default_profile(self) -> Optional[Dict[str, Any]]:
        """Get the default tax profile."""
        return await self._repo.find_default()

    async def update_profile(
        self, gstin: str, update_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a tax profile."""
        doc = await self._repo.update_one(
            {"data.gstin": gstin},
            update_data,
        )
        if not doc:
            not_found(message=f"Tax profile with GSTIN '{gstin}' not found.")
        return doc

    @staticmethod
    def preview_tax(
        line_items: List[Dict[str, Any]],
        seller_gstin: str = "",
        place_of_supply: str = "",
    ) -> Dict[str, Any]:
        """
        Preview tax computation without creating an invoice.

        Used by the frontend to show tax breakdown before saving.
        """
        line_results = []
        tax_inputs: list[tuple[float, str]] = []

        for item in line_items:
            taxable = float(item.get("taxable_amount", 0))
            tax_cat = item.get("tax_category", "higher")

            line_tax = compute_line_tax(
                taxable_amount=taxable,
                tax_category=tax_cat,
                seller_gstin=seller_gstin,
                place_of_supply=place_of_supply,
            )
            line_results.append(line_tax.to_dict())
            tax_inputs.append((taxable, tax_cat))

        aggregate = compute_invoice_tax(
            line_taxable_amounts=tax_inputs,
            seller_gstin=seller_gstin,
            place_of_supply=place_of_supply,
        )

        return {
            "line_taxes": line_results,
            "aggregate": aggregate.to_dict(),
        }
