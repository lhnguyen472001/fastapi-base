"""Auth-domain enumerations."""

from __future__ import annotations

import enum


class TokenType(enum.StrEnum):
    """JWT ``type`` claim — prevents token confusion across auth flows.

    The wire-format string values are stable; do not change them without a
    coordinated rotation, since they are embedded in already-issued JWTs.
    """

    ACCESS = "access"
    REFRESH = "refresh"
    CHALLENGE = "2fa_challenge"
