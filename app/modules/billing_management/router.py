"""
Billing Management Router — aggregates all sub-routers.

All billing endpoints are mounted under /billing (set by api_router.py).
Sub-routers:
  /billing/catalog/*       → Catalog CRUD
  /billing/invoices/*      → Invoice lifecycle
  /billing/payments/*      → Payment recording
  /billing/tax/*           → Tax profiles + GST preview
"""

from fastapi import APIRouter

from app.modules.billing_management.routes.catalog_routes import (
    router as catalog_router,
)
from app.modules.billing_management.routes.invoice_routes import (
    router as invoice_router,
)
from app.modules.billing_management.routes.payment_routes import (
    router as payment_router,
)
from app.modules.billing_management.routes.tax_routes import (
    router as tax_router,
)

router = APIRouter()

router.include_router(catalog_router, prefix="/catalog", tags=["billing-catalog"])
router.include_router(invoice_router, prefix="/invoices", tags=["billing-invoices"])
router.include_router(payment_router, prefix="/payments", tags=["billing-payments"])
router.include_router(tax_router, prefix="/tax", tags=["billing-tax"])
