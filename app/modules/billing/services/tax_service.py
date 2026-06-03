"""
Tax Service — tax profile management and tax computation API.

Wraps the pure TaxEngine with database operations for GSTIN
profile CRUD. Uses Beanie ODM (TaxProfileDoc) for all MongoDB
interactions — no manual Motor queries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, conflict, not_found
from app.core.context import OrgContext
from app.core.logger import create_logger
from app.modules.billing.constants import ENTITY_TAX_PROFILE
from app.modules.billing.documents.tax_profile_doc import TaxProfileDoc
from app.modules.billing.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
)

logger = create_logger("billing.tax_service")


class TaxService:
    """Tax profile management and GST computation using Beanie ORM."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx

    async def create_profile(self, data: Dict[str, Any]) -> TaxProfileDoc:
        """Create a new tax profile (GSTIN registration)."""
        gstin = data.get("gstin", "").strip()
        if not gstin:
            bad_request(message="GSTIN is required.")

        # Duplicate GSTIN check within the org
        existing = await TaxProfileDoc.find_by_gstin(self._ctx, gstin)
        if existing:
            conflict(
                message=f"A tax profile with GSTIN '{gstin}' already exists.",
                error_code="DUPLICATE_GSTIN",
            )

        # If this is set as default, unset any existing default
        if data.get("is_default"):
            current_default = await TaxProfileDoc.find_default(self._ctx)
            if current_default:
                current_default.is_default = False
                await current_default.org_save(self._ctx)

        # Build Beanie document with auto org-scoping
        doc = TaxProfileDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_TAX_PROFILE,
            record_id=f"TAX-{gstin[-4:]}",
            profile_name=data.get("profile_name", ""),
            gstin=gstin,
            legal_name=data.get("legal_name", ""),
            trade_name=data.get("trade_name", ""),
            state_code=data.get("state_code", ""),
            state_name=data.get("state_name", ""),
            tax_type=data.get("tax_type", "gst"),
            default_tax_category=data.get("default_tax_category", "higher"),
            is_composition_scheme=data.get("is_composition_scheme", False),
            is_default=data.get("is_default", False),
        )

        await doc.insert()
        logger.info("Created tax profile gstin=%s org=%s", gstin, self._ctx.org_id)
        return doc

    async def list_profiles(
        self, *, skip: int = 0, limit: int = 50,
    ) -> tuple[List[TaxProfileDoc], int]:
        """List all tax profiles for the org."""
        documents = await TaxProfileDoc.list_all(
            self._ctx, skip=skip, limit=limit,
        )
        total = await TaxProfileDoc.org_count(self._ctx)
        return documents, total

    async def get_default_profile(self) -> Optional[TaxProfileDoc]:
        """Get the default tax profile."""
        return await TaxProfileDoc.find_default(self._ctx)

    async def update_profile(
        self, gstin: str, update_data: Dict[str, Any],
    ) -> TaxProfileDoc:
        """Update a tax profile by its GSTIN."""
        doc = await TaxProfileDoc.find_by_gstin(self._ctx, gstin)
        if not doc:
            not_found(message=f"Tax profile with GSTIN '{gstin}' not found.")

        # Apply field updates from the payload
        for field_name, value in update_data.items():
            if hasattr(doc, field_name):
                setattr(doc, field_name, value)

        await doc.org_save(self._ctx)
        logger.info("Updated tax profile gstin=%s org=%s", gstin, self._ctx.org_id)
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
