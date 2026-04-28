"""Health-check endpoint."""

from fastapi import APIRouter

from apps.core.schemas.response import APIResponse
from apps.settings import app_settings

health_router = APIRouter(tags=["health"])


@health_router.get("/health", response_model=APIResponse[dict])
async def health() -> APIResponse[dict]:
    """Liveness probe — returns 200 when the process is up."""
    return APIResponse[dict].success(
        data={"status": "ok", "app": app_settings.app_name},
        message="OK",
    )
