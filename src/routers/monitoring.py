"""Health and monitoring endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..modules.pipeline.llm.rate_limiter import get_rate_limiter

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint.

    Returns service status and rate limiter statistics.
    """
    try:
        # Get rate limiter stats
        rate_limiter = get_rate_limiter()
        stats = rate_limiter.get_stats()

        # Get cache stats from orchestrator
        from ..modules.assistant import orchestrator as orch_module

        cache_stats = {}
        if hasattr(orch_module, "orchestrator") and orch_module.orchestrator:
            cache_stats = orch_module.orchestrator.cache.get_stats()

        return JSONResponse(
            content={
                "status": "healthy",
                "service": "invoice-platform",
                "components": {
                    "api": "operational",
                    "pipeline": "operational",
                    "assistant": "operational",
                },
                "rate_limits": {
                    "usage": stats["usage"],
                    "limits": stats["limits"],
                    "remaining": stats["remaining"],
                    "breakdown": stats.get("breakdown", {}),
                    "health": _get_rate_limit_health(stats),
                },
                "cache": cache_stats,
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
            },
        )


@router.get("/metrics")
async def metrics() -> JSONResponse:
    """
    Detailed metrics endpoint.

    Returns comprehensive rate limiter statistics.
    """
    try:
        rate_limiter = get_rate_limiter()
        stats = rate_limiter.get_stats()

        return JSONResponse(
            content={
                "llm_api": {
                    "usage": stats["usage"],
                    "limits": stats["limits"],
                    "remaining": stats["remaining"],
                    "breakdown": stats.get("breakdown", {}),
                    "utilization": {
                        "rpm": _calculate_utilization(
                            stats["usage"]["rpm"], stats["limits"]["rpm"]
                        ),
                        "rpd": _calculate_utilization(
                            stats["usage"]["rpd"], stats["limits"]["rpd"]
                        ),
                        "tpm": _calculate_utilization(
                            stats["usage"]["tpm"], stats["limits"]["tpm"]
                        ),
                        "tpd": _calculate_utilization(
                            stats["usage"]["tpd"], stats["limits"]["tpd"]
                        ),
                    },
                },
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.post("/rate-limiter/reset")
async def reset_rate_limiter_endpoint() -> JSONResponse:
    """
    Reset rate limiter counters.

    ⚠️ USE WITH CAUTION: This resets all tracked usage.
    Only use this if you know the actual LLM provider limits have reset
    or for testing purposes.
    """
    try:
        from ..modules.pipeline.llm.rate_limiter import reset_rate_limiter

        reset_rate_limiter()

        return JSONResponse(
            content={
                "status": "success",
                "message": "Rate limiter has been reset. All usage counters cleared.",
                "warning": "Make sure actual LLM API limits have reset to avoid 429 errors.",
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


def _calculate_utilization(current: int, limit: int) -> float:
    """Calculate percentage utilization."""
    if limit == 0:
        return 0.0
    return round((current / limit) * 100, 2)


def _get_rate_limit_health(stats: dict) -> str:
    """
    Determine rate limit health status.

    Returns:
        - "healthy": < 70% utilization
        - "warning": 70-90% utilization
        - "critical": > 90% utilization
    """
    max_util = 0.0

    for key in ["rpm", "rpd", "tpm", "tpd"]:
        current = stats["usage"][key]
        limit = stats["limits"][key]
        if limit > 0:
            util = current / limit
            max_util = max(max_util, util)

    if max_util < 0.7:
        return "healthy"
    elif max_util < 0.9:
        return "warning"
    else:
        return "critical"
