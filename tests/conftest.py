"""Root pytest configuration."""

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio backend for anyio-based async tests."""
    return "asyncio"
