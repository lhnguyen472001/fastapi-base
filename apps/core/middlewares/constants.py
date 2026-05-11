"""Module-level constants for cross-cutting middlewares."""

from typing import Final

REQUEST_ID_HEADER: Final[str] = "x-request-id"
REQUEST_ID_FALLBACK: Final[str] = "-"
