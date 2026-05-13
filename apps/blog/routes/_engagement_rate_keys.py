"""slowapi ``key_func`` helpers for the engagement endpoints.

The route layer runs the limiter BEFORE the FastAPI dependency tree, so
``current_user.id`` isn't available at limit-evaluation time. These
helpers extract a stable per-caller key:

* :func:`auth_user_key` — the JWT subject claim (parsed *without*
  signature verification, used purely for keying — the route's auth
  dependency still rejects invalid tokens). Falls back to source IP for
  unauthenticated requests.
* :func:`anonymous_ip_key` — always the source IP. Use for endpoints
  that accept anonymous traffic alongside authenticated traffic.

Both helpers respect the trusted forwarded-IP header through slowapi's
:func:`slowapi.util.get_remote_address` (which the project's existing
rate-limit integration already relies on).
"""

from __future__ import annotations

import jwt
from fastapi import Request
from slowapi.util import get_remote_address

__all__ = ("anonymous_ip_key", "auth_user_key")


def _try_extract_jwt_sub(authorization: str | None) -> str | None:
    """Return the JWT ``sub`` claim without verifying the signature.

    Used only for rate-limit keying; the actual auth dependency on the
    route enforces signature + expiry. An attacker could spoof the
    ``sub`` to consume someone else's rate budget — that's defensive
    enough for a public-facing limiter and the worst case is an
    annoying-but-recoverable 429 for the spoofed user.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer ") :]
    try:
        payload = jwt.decode(  # type: ignore[no-untyped-call]
            token,
            options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
        )
    except Exception:
        return None
    sub = payload.get("sub")
    return str(sub) if sub is not None else None


def auth_user_key(request: Request) -> str:
    """Key authenticated bearer requests by JWT ``sub``; anonymous by IP."""
    sub = _try_extract_jwt_sub(request.headers.get("authorization"))
    if sub is not None:
        return f"user:{sub}"
    return f"ip:{get_remote_address(request)}"


def anonymous_ip_key(request: Request) -> str:
    """Always key by source IP — used by the anonymous-comment limiter (FR-024b)."""
    return f"ip:{get_remote_address(request)}"
