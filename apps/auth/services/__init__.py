"""Auth services package.

Layout:

* :mod:`._tokens` — :class:`TokenService` (refresh/access-token lifecycle)
* :mod:`._email_verification` — :class:`EmailVerificationService` (OTP flow)
* :mod:`._two_factor` — :class:`TwoFactorService` (TOTP setup / enable /
  disable / verify)
* :mod:`._oauth` — :class:`OAuthService` (Google OAuth exchange + state)
* :mod:`._auth` — :class:`AuthService`, the facade that composes the above
  and keeps the pre-split public method set for backward compatibility.

Routes, dependencies, and tests import ``AuthService`` from this package
exactly as before the split.
"""

from __future__ import annotations

from apps.auth.services._auth import AuthService
from apps.auth.services._email_verification import EmailVerificationService
from apps.auth.services._oauth import OAuthService
from apps.auth.services._tokens import TokenService
from apps.auth.services._two_factor import TwoFactorService

__all__ = [
    "AuthService",
    "EmailVerificationService",
    "OAuthService",
    "TokenService",
    "TwoFactorService",
]
