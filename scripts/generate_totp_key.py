"""Print a fresh Fernet key for the TOTP-secret encryption setting.

Usage:
    uv run python scripts/generate_totp_key.py

Copy the printed value into your environment as ``AUTH_TOTP_ENCRYPTION_KEY``.
The key is 32 random bytes encoded as 44 url-safe base64 chars and is the
only credential needed to encrypt / decrypt the ``users.totp_secret`` column.
"""

from __future__ import annotations

import sys

from cryptography.fernet import Fernet


def main() -> int:
    sys.stdout.write(Fernet.generate_key().decode("ascii") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
