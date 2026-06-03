"""
BaseBillingService — abstract base class for all billing service domains.

Every billing sub-service inherits from this class, gaining:
  - Shared db + ctx access (org-scoped request context)
  - Auto-configured structured logging per service domain
  - Billing number generation via sequence_helpers (template method)
  - Consistent service_name / entity_type identity

Concrete services implement the abstract properties and add
their domain-specific public methods (create, get, list, etc.).

Hierarchy:
    BaseBillingService (ABC)
    ├── OrderService       — order lifecycle
    ├── InvoiceService     — invoice lifecycle
    ├── PaymentService     — payment recording
    ├── CreditNoteService  — refunds & credits
    ├── ReceiptService     — read-only receipts
    └── TaxProfileService  — tax profile management
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.context import OrgContext
from app.core.logger import create_logger
from app.modules.billing.utils.sequence_helpers import generate_billing_number


class BaseBillingService(ABC):
    """
    Abstract base for all billing service domains.

    Provides shared infrastructure: database access, org context,
    structured logging, and billing number generation.

    Subclasses MUST implement:
      - service_name: str — unique identifier for logging
      - entity_type: str — the _meta.entity_type for documents

    Subclasses MAY override:
      - number_prefix: str — enable auto-numbered documents
      - _generate_number() — custom numbering logic
    """

    __slots__ = ("_db", "_ctx", "_logger")

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        """
        Initialize the service with database and org context.

        Args:
            db: Motor async database instance.
            ctx: Current request's org context (from JWT + headers).
        """
        self._db = db
        self._ctx = ctx
        self._logger = create_logger(f"billing.{self.service_name}")

    # ── Abstract Properties (MUST implement) ─────────────────────

    @property
    @abstractmethod
    def service_name(self) -> str:
        """
        Unique service identifier for logging and tracing.

        Examples: 'orders', 'invoices', 'payments', 'credit_notes'.
        Used to create the logger name: 'billing.{service_name}'.
        """
        ...

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """
        The _meta.entity_type this service manages.

        Must match the ENTITY_* constant from billing.constants.
        Examples: 'order', 'invoice', 'payment', 'credit_note'.
        """
        ...

    # ── Concrete Properties (MAY override) ───────────────────────

    @property
    def number_prefix(self) -> str:
        """
        Prefix for auto-numbered billing documents.

        Override in subclasses that generate sequential numbers
        (e.g., 'INV', 'PAY', 'ORD', 'CN', 'RCT').

        Returns empty string by default — indicates no auto-numbering.
        Services like TaxProfileService that use custom IDs (GSTIN-based)
        leave this empty and override _generate_number() instead.
        """
        return ""

    # ── Billing Number Generation ────────────────────────────────

    async def _generate_number(self) -> str:
        """
        Generate next sequential billing number.

        Format: {prefix}/{FY}/{counter:04d}
        Examples: INV/2026-27/0001, PAY/2026-27/0003

        Uses shared sequence_helpers for atomic, org-scoped,
        FY-scoped counter generation. Override for custom
        numbering logic (e.g., TaxProfileService uses
        GSTIN-based IDs instead of sequential numbers).

        Raises:
            NotImplementedError: If number_prefix is empty and
                this method is not overridden.
        """
        if not self.number_prefix:
            raise NotImplementedError(
                f"{self.service_name} does not support auto-numbering. "
                f"Override number_prefix or _generate_number()."
            )
        return await generate_billing_number(
            self._db,
            self._ctx,
            prefix=self.number_prefix,
            entity_key=self.entity_type,
        )
