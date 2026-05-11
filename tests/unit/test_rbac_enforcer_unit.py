"""Unit tests for ``apps.rbac.enforcer._build_watcher_options``.

The helper translates a Redis URL string into the ``WatcherOptions`` object
required by :func:`casbin_redis_watcher.new_watcher`. Prior to this helper
the URL was passed through as-is and the library crashed with
``AttributeError("'str' object has no attribute 'init_config'")`` during
worker startup. These tests pin the URL -> options mapping so the regression
cannot return silently.
"""

from __future__ import annotations

import pytest
from casbin_redis_watcher import WatcherOptions

from apps.rbac.enforcer import _build_watcher_options


@pytest.mark.unit
def test_simple_redis_url_maps_host_port_no_password() -> None:
    options = _build_watcher_options("redis://redis:6379/0")

    assert isinstance(options, WatcherOptions)
    assert options.host == "redis"
    assert options.port == 6379
    assert options.password is None
    assert options.ssl is False


@pytest.mark.unit
def test_password_is_extracted_from_userinfo() -> None:
    options = _build_watcher_options("redis://:s3cret@cache.internal:6380/2")

    assert options.host == "cache.internal"
    assert options.port == 6380
    assert options.password == "s3cret"
    assert options.ssl is False


@pytest.mark.unit
def test_rediss_scheme_enables_ssl() -> None:
    options = _build_watcher_options("rediss://cache.example:6380")

    assert options.host == "cache.example"
    assert options.port == 6380
    assert options.ssl is True


@pytest.mark.unit
def test_missing_port_falls_back_to_default() -> None:
    options = _build_watcher_options("redis://redis")

    assert options.host == "redis"
    assert options.port == 6379


@pytest.mark.unit
def test_non_redis_scheme_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must use redis:// or rediss://"):
        _build_watcher_options("http://redis:6379")
