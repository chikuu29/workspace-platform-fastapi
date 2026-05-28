"""
MongoDB Connection Manager — async Motor client with lifespan-scoped lifecycle.

Uses Motor's AsyncIOMotorClient with connection pooling. The client is created
once during startup (lifespan) and shared across all requests via FastAPI's
dependency injection system.

Usage:
    from app.db.database import get_database
    db: AsyncIOMotorDatabase = Depends(get_database)
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# ── Beanie ODM & Motor Compatibility Patch ──────────────────────────────────
# Beanie 2.1.0 attempts to append metadata via database.client.append_metadata.
# In Motor, accessing undefined attributes dynamically returns a MotorDatabase,
# which is callable (but raises TypeError upon invocation). Defining a dummy
# method prevents Motor's collection/database lookup logic from triggering.
AsyncIOMotorClient.append_metadata = lambda self, *args, **kwargs: None

from beanie import init_beanie

from app.core.config import settings
from app.core.logger import create_logger

logger = create_logger("database")

# ── Module-level singleton — populated by lifespan events ────────────────
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    """
    Initialize the Motor client and verify connectivity.

    Called once during FastAPI lifespan startup. Performs a server ping
    to fail-fast if MongoDB is unreachable — no silent misconfigurations.
    """
    global _client, _db

    _client = AsyncIOMotorClient(
        settings.MONGO_URI,
        # Motor defaults are sane, but let's be explicit about pool sizing
        maxPoolSize=50,
        minPoolSize=5,
        serverSelectionTimeoutMS=5000,
    )
    _db = _client[settings.DATABASE_NAME]

    # Verify the connection actually works — fail fast at startup
    try:
        await _client.admin.command("ping")
        logger.info(
            "Connected to MongoDB: %s (db: %s)",
            settings.MONGO_URI.split("@")[-1] if "@" in settings.MONGO_URI else settings.MONGO_URI,
            settings.DATABASE_NAME,
        )

        # ── Create indexes for the unified records collection ────────
        await _ensure_indexes(_db)

        # ── Initialize Beanie ODM ───────────────────────────────────────────
        from app.modules.billing_management.documents.invoice_doc import InvoiceDoc
        from app.modules.billing_management.documents.payment_doc import PaymentDoc

        await init_beanie(
            database=_db,
            document_models=[InvoiceDoc, PaymentDoc]
        )
        logger.info("Beanie ODM initialized for billing models")

    except Exception as e:
        logger.error("MongoDB connection failed: %s", e)
        raise


async def close_mongo_connection() -> None:
    """Gracefully close the Motor client during shutdown."""
    global _client, _db

    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("Closed MongoDB connection")


def get_database() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency for database access.

    Returns the shared AsyncIOMotorDatabase instance.
    Always use via Depends(get_database) — never call directly in route handlers.

    Raises:
        RuntimeError: If called before lifespan startup (connect_to_mongo).
    """
    if _db is None:
        raise RuntimeError(
            "Database not initialized — ensure connect_to_mongo() "
            "was called during application startup."
        )
    return _db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create compound indexes for the unified `records` collection.

    These indexes are idempotent — MongoDB skips creation if they
    already exist. Called once during startup.
    """
    records = db["records"]

    # Primary lookup: all records for an org + entity type, newest first
    await records.create_index(
        [("_org.org_id", 1), ("_meta.entity_type", 1), ("_meta.created.at", -1)],
        name="idx_org_entity_created",
        background=True,
    )

    # Unique record_id per org (prevents duplicate sequence IDs)
    await records.create_index(
        [("_org.org_id", 1), ("_meta.record_id", 1)],
        name="idx_org_record_id",
        unique=True,
        background=True,
    )

    # Soft-delete filter — covers active_filter queries
    await records.create_index(
        [("_org.org_id", 1), ("_meta.is_deleted", 1)],
        name="idx_org_deleted",
        background=True,
    )

    logger.info("MongoDB indexes ensured for 'records' collection")

    # ── Billing Collection Indexes ───────────────────────────────────────
    # Separate collections for the centralized billing module.
    # Each index is idempotent — safe to call on every startup.

    # Invoices: overdue lookup, unique invoice numbers, customer history
    await db["billing_invoices"].create_index(
        [("_org.org_id", 1), ("data.status", 1), ("data.due_date", 1)],
        name="idx_bill_inv_status_due", background=True,
    )
    await db["billing_invoices"].create_index(
        [("_org.org_id", 1), ("data.invoice_number", 1)],
        name="idx_bill_inv_number", unique=True, background=True,
    )
    await db["billing_invoices"].create_index(
        [("_org.org_id", 1), ("data.customer_ref.ref_id", 1)],
        name="idx_bill_inv_customer", background=True,
    )

    # Payments: invoice lookup, gateway tier filtering
    await db["billing_payments"].create_index(
        [("_org.org_id", 1), ("data.invoice_ref", 1)],
        name="idx_bill_pay_invoice", background=True,
    )
    await db["billing_payments"].create_index(
        [("_org.org_id", 1), ("data.gateway_tier", 1), ("data.status", 1)],
        name="idx_bill_pay_tier_status", background=True,
    )

    # Subscriptions: renewal processing
    await db["billing_subscriptions"].create_index(
        [("_org.org_id", 1), ("data.status", 1), ("data.next_billing_date", 1)],
        name="idx_bill_sub_renewal", background=True,
    )

    # Gateway configs: one active config per org+app
    await db["billing_gateway_configs"].create_index(
        [("_org.org_id", 1), ("_org.app_code", 1)],
        name="idx_bill_gw_org_app", unique=True, background=True,
    )

    # Settlements: status lookup
    await db["billing_settlements"].create_index(
        [("_org.org_id", 1), ("data.status", 1)],
        name="idx_bill_stl_status", background=True,
    )

    # Reminders: scheduled processing
    await db["billing_reminders"].create_index(
        [("data.status", 1), ("data.scheduled_date", 1)],
        name="idx_bill_rem_scheduled", background=True,
    )



    # Tax profiles: GSTIN lookup
    await db["billing_tax_profiles"].create_index(
        [("_org.org_id", 1), ("data.gstin", 1)],
        name="idx_bill_tax_gstin", unique=True, background=True,
    )

    logger.info("MongoDB indexes ensured for billing collections")

