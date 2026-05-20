"""Protocol types for the Auth module.

* Re-exports :class:`apps.user.repositories.UserRepositoryProtocol` so the
  auth sub-services can depend on a protocol owned by their own module
  namespace (FR-021), avoiding cross-module concrete imports.
* Declares :class:`OAuthProviderProtocol` and the carrier dataclass
  :class:`OAuthUserInfo` so the auth services depend on a generic
  contract instead of the concrete Google client. Adding a new provider
  (Microsoft, Apple, GitHub) becomes "write a class that satisfies this
  protocol" — the DI container, services, and tests don't need to know
  about the concrete implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.user.repositories import UserRepositoryProtocol

__all__ = [
    "OAuthProviderProtocol",
    "OAuthUserInfo",
    "UserRepositoryProtocol",
]


@dataclass(slots=True, kw_only=True, frozen=True)
class OAuthUserInfo:
    """Provider-neutral subset of an OAuth2 userinfo response.

    The fields are the smallest common set our linking flow requires.
    Provider-specific extras (e.g. Google's ``hd`` workspace domain)
    should live on a provider-specific value object, not here.
    """

    sub: str
    email: str
    email_verified: bool
    name: str | None = None
    picture: str | None = None


class OAuthProviderProtocol(Protocol):
    """Surface every OAuth2 provider client must satisfy.

    The auth services depend on this protocol; DI wires a concrete
    implementation. Today that is :class:`GoogleOAuthClient`; tomorrow
    it can be a Microsoft / Apple / GitHub client without touching
    service code or tests beyond the container binding.
    """

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Build the consent-screen URL the browser is redirected to.

        ``state`` is the CSRF token the caller will validate on
        callback; ``code_challenge`` is the PKCE S256 challenge derived
        from a server-side ``code_verifier``.
        """
        ...

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthUserInfo:
        """Exchange an authorization code + PKCE verifier for userinfo.

        Implementations contact the provider's token + userinfo
        endpoints and return an :class:`OAuthUserInfo`. They must raise
        :class:`apps.auth.exceptions.OAuthProviderError` on transport
        failures or rejected codes.
        """
        ...

    async def aclose(self) -> None:
        """Close any long-lived transport resources (e.g. ``httpx.AsyncClient``)."""
        ...
