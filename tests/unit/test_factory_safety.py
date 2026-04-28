"""Unit tests for the multi-worker safety check in ``apps.factory``."""

from __future__ import annotations

import pytest

from apps.factory import verify_rbac_multi_worker_safety
from apps.settings import app_settings


def test_safety_check_passes_with_single_worker(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "workers", 1)
    monkeypatch.setattr(app_settings.rbac, "watcher_redis_url", None)

    verify_rbac_multi_worker_safety()  # no raise


def test_safety_check_passes_with_multi_worker_and_watcher(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "workers", 4)
    monkeypatch.setattr(app_settings.rbac, "watcher_redis_url", "redis://localhost:6379/0")

    verify_rbac_multi_worker_safety()  # no raise


def test_safety_check_raises_when_multi_worker_and_no_watcher(monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "workers", 4)
    monkeypatch.setattr(app_settings.rbac, "watcher_redis_url", None)

    with pytest.raises(RuntimeError, match="WORKERS=4"):
        verify_rbac_multi_worker_safety()


def test_safety_check_raises_when_multi_worker_and_empty_string_watcher(monkeypatch) -> None:
    """Empty string from env-loaded settings must be treated as unset."""
    monkeypatch.setattr(app_settings, "workers", 2)
    monkeypatch.setattr(app_settings.rbac, "watcher_redis_url", "")

    with pytest.raises(RuntimeError):
        verify_rbac_multi_worker_safety()
