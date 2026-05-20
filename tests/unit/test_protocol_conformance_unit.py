"""Unit tests for MED-4: concrete adapters satisfy their Protocol contracts.

Protocols use structural typing — a concrete class doesn't need to
inherit the Protocol to satisfy it. These tests pin the structural
match so that an accidental rename / signature change on either side
fails CI before it ships, instead of surfacing as a runtime
``AttributeError`` deep in a request handler.

Covers:

* :class:`OAuthProviderProtocol` ↔ :class:`GoogleOAuthClient`
* :class:`StorageAdapterProtocol` ↔ :class:`S3Client`
* :class:`OAuthUserInfo` carrier fields (sub / email / email_verified
  / name / picture) — the union of fields the auth services read.
"""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints

import pytest

from apps.auth.oauth.google import GoogleOAuthClient, GoogleUserInfo
from apps.auth.protocols import OAuthProviderProtocol, OAuthUserInfo
from apps.core.storage import StorageAdapterProtocol
from apps.core.storage.s3 import S3Client


def _protocol_method_names(proto: type[Protocol]) -> set[str]:
    """Return the public method names declared on a Protocol class.

    Filters out dunders and inherited ``Protocol`` machinery so the
    comparison is only over the surface the protocol actually declares.
    """
    return {
        name
        for name, value in vars(proto).items()
        if not name.startswith("_") and callable(value)
    }


def _assert_satisfies_protocol(concrete: type, proto: type[Protocol]) -> None:
    """Assert every method the protocol declares exists on the concrete class
    with a compatible signature (same param names; required kwargs preserved)."""
    proto_methods = _protocol_method_names(proto)
    missing = [name for name in proto_methods if not hasattr(concrete, name)]
    assert missing == [], f"{concrete.__name__} is missing protocol methods: {missing}"

    for name in proto_methods:
        proto_sig = inspect.signature(getattr(proto, name))
        concrete_sig = inspect.signature(getattr(concrete, name))
        proto_params = {p for p in proto_sig.parameters if p != "self"}
        concrete_params = {p for p in concrete_sig.parameters if p != "self"}
        missing_params = proto_params - concrete_params
        assert missing_params == set(), (
            f"{concrete.__name__}.{name} missing params required by {proto.__name__}: {missing_params}"
        )


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


def test_google_oauth_client_satisfies_oauth_provider_protocol() -> None:
    _assert_satisfies_protocol(GoogleOAuthClient, OAuthProviderProtocol)


def test_google_oauth_client_exchange_code_is_coroutine() -> None:
    assert inspect.iscoroutinefunction(GoogleOAuthClient.exchange_code)


def test_google_oauth_client_aclose_is_coroutine() -> None:
    assert inspect.iscoroutinefunction(GoogleOAuthClient.aclose)


def test_google_user_info_is_oauth_user_info_alias() -> None:
    """Legacy ``GoogleUserInfo`` must alias the canonical protocol type
    so existing imports keep working after the protocol extraction."""
    assert GoogleUserInfo is OAuthUserInfo


def test_oauth_user_info_carries_the_documented_fields() -> None:
    """The auth services read sub/email/email_verified/name/picture —
    pin the field set so a refactor that drops one is caught here, not
    in a 500 response."""
    hints = get_type_hints(OAuthUserInfo)
    assert {"sub", "email", "email_verified", "name", "picture"} <= set(hints)


def test_oauth_user_info_is_frozen_dataclass() -> None:
    """Frozen dataclass — mutating an OAuthUserInfo from a service must
    raise instead of silently corrupting cached values."""
    info = OAuthUserInfo(sub="abc", email="x@y", email_verified=True)
    with pytest.raises(AttributeError):
        info.email = "z@y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_s3_client_satisfies_storage_adapter_protocol() -> None:
    _assert_satisfies_protocol(S3Client, StorageAdapterProtocol)


@pytest.mark.parametrize(
    "method_name",
    [
        "generate_presigned_post",
        "generate_presigned_get_url",
        "head_object",
        "delete_object",
    ],
)
def test_s3_client_storage_methods_are_coroutines(method_name: str) -> None:
    assert inspect.iscoroutinefunction(getattr(S3Client, method_name))
