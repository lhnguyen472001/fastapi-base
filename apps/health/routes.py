"""Health-check endpoint."""

from fastapi import APIRouter

from apps.core.schemas.response import (
    APIResponse,
    JsonResponseStatuses,
    ResponseCodes,
)
from apps.settings import app_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=APIResponse[dict])
async def health() -> APIResponse[dict]:
    """Liveness probe — returns 200 when the process is up."""
    return APIResponse[dict](
        code=ResponseCodes.API000,
        data={"status": "ok", "app": app_settings.app_name},
        status=JsonResponseStatuses.SUCCESS,
        message="OK",
    )
