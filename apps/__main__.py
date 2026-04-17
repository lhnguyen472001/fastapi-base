"""Package entrypoint: ``python -m apps`` / ``uv run apps``.

Loads the FastAPI app from :mod:`apps.factory` and serves it via uvicorn,
honoring host/port/reload/workers from :mod:`apps.settings`.
"""

from __future__ import annotations

import uvicorn

from apps.settings import app_settings


def main() -> None:
    """Run the API server using settings from the environment."""
    uvicorn.run(
        "apps.factory:app",
        host=app_settings.host,
        port=app_settings.port,
        reload=app_settings.reload,
        workers=app_settings.workers if not app_settings.reload else 1,
    )


if __name__ == "__main__":
    main()
