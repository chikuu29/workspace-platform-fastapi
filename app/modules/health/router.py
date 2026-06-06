"""
Health Check Router — liveness and readiness probes for MongoDB.

Provides endpoints for Kubernetes liveness and readiness probes,
load balancers, and infrastructure monitoring.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.database import get_db
from app.core.logger import create_logger

logger = create_logger("health")

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """
    Combined health check — verifies MongoDB connectivity.

    Returns 200 if all backing services are reachable, 503 if degraded.
    Used by ArgoCD sync health checks and load balancers.
    """
    health: dict = {"status": "healthy", "services": {}}
    overall_healthy = True

    # Check MongoDB — attempt a ping on the admin database
    try:
        db = get_db()
        await db.client.admin.command("ping")
        health["services"]["mongodb"] = {"status": "healthy"}
    except Exception as exc:
        health["services"]["mongodb"] = {"status": "unhealthy", "error": str(exc)}
        overall_healthy = False
        logger.error("Health check: MongoDB unhealthy — %s", str(exc))

    if not overall_healthy:
        health["status"] = "degraded"

    return JSONResponse(
        content=health,
        status_code=200 if overall_healthy else 503,
    )


@router.get("/health/live")
async def liveness() -> dict:
    """
    Kubernetes liveness probe — always returns 200 if the process is alive.

    If this endpoint is unreachable, Kubernetes considers the pod dead and
    kills + restarts it. It should NEVER check external services.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """
    Kubernetes readiness probe — returns 200 only when MongoDB is reachable.

    While not ready, the pod is removed from the Service's endpoint slice
    and receives no traffic — preventing 503s during startup or DB outages.
    """
    try:
        db = get_db()
        await db.client.admin.command("ping")
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception as exc:
        logger.error("Readiness check failed: %s", str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "error": str(exc)},
        )
