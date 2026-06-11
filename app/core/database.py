"""
MongoDB Connection Manager — async Motor client with lifespan-scoped lifecycle.

Uses Motor's AsyncIOMotorClient with connection pooling. The client is created
once during startup (lifespan) and shared across all requests via FastAPI's
dependency injection system.

Usage:
    from app.core.database import get_db
    db: AsyncIOMotorDatabase = Depends(get_db)
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


async def connect_db() -> None:
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

        # Drop existing indexes on the billing collections to avoid conflicts with new schema structure
        from app.modules.billing.documents.order_doc import OrderDoc
        from app.modules.billing.documents.invoice_doc import InvoiceDoc
        from app.modules.billing.documents.payment_doc import PaymentDoc
        from app.modules.billing.documents.credit_note_doc import CreditNoteDoc
        from app.modules.billing.documents.receipt_doc import ReceiptDoc
        from app.modules.billing.documents.tax_profile_doc import TaxProfileDoc

        billing_collections = ["orders", "invoices", "payments", "credit_notes", "receipts", "tax_profiles"]
        for coll_name in billing_collections:
            try:
                await _db[coll_name].drop_indexes()
                logger.info("Dropped indexes on collection: %s", coll_name)
            except Exception as e:
                logger.debug("Could not drop indexes on %s: %s", coll_name, e)

        await init_beanie(
            database=_db,
            document_models=[
                OrderDoc,
                InvoiceDoc,
                PaymentDoc,
                CreditNoteDoc,
                ReceiptDoc,
                TaxProfileDoc,
            ],
        )
        logger.info("Beanie ODM initialized for all billing document models")

    except Exception as e:
        logger.error("MongoDB connection failed: %s", e)
        raise


async def close_db() -> None:
    """Gracefully close the Motor client during shutdown."""
    global _client, _db

    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("Closed MongoDB connection")


def get_db() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency for database access.

    Returns the shared AsyncIOMotorDatabase instance.
    Always use via Depends(get_db) — never call directly in route handlers.

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

    NOTE: Billing collection indexes are now managed by Beanie via
    each document's Settings.indexes. The manual indexes below are
    ONLY for the shared `records` collection used by non-billing modules.
    """
    records = db["records"]

    # Primary lookup: all records for an org + entity type, newest first
    await records.create_index(
        [("_org.org_id", 1), ("_meta.entity_type", 1), ("_meta.created.at", -1)],
        name="idx_org_entity_created",
        background=True,
    )

    # Unique id per org (prevents duplicate sequence IDs)
    await records.create_index(
        [("_org.org_id", 1), ("_meta.id", 1)],
        name="idx_org_id",
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
    # Billing collection indexes are auto-managed by Beanie's Settings.indexes
    # in each document class. No manual Motor index creation needed here.
    logger.info("Billing indexes delegated to Beanie document Settings.indexes")
