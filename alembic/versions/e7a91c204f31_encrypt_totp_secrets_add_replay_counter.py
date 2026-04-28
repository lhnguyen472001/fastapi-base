"""encrypt totp secrets at rest, add replay-guard counter

Revision ID: e7a91c204f31
Revises: d25eb50aab99
Create Date: 2026-04-28

Widens ``users.totp_secret`` from varchar(64) to varchar(255) so it can hold
Fernet ciphertext (~100 chars), encrypts every existing non-NULL secret in
place using ``apps.core.security.encrypt_totp_secret``, and adds the
``users.last_totp_counter`` BigInteger column used by the replay guard in
``apps.auth.services.TwoFactorService``.

Backfill is idempotent: rows whose ``totp_secret`` length already exceeds
64 chars are treated as already-encrypted and skipped. ``downgrade()``
intentionally raises because dropping the encryption requires plaintext
recovery via the key, which alembic should never do silently.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a91c204f31"
down_revision: str | Sequence[str] | None = "d25eb50aab99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "totp_secret",
        type_=sa.String(255),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
    op.add_column(
        "users",
        sa.Column("last_totp_counter", sa.BigInteger(), nullable=True),
    )

    from apps.auth.security import encrypt_totp_secret

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL"),
    ).fetchall()
    for row_id, plaintext in rows:
        # Already-encrypted Fernet tokens are ~100 chars URL-safe base64 and
        # always exceed the legacy 64-char ceiling. Plaintext base32 secrets
        # from pyotp.random_base32() default to 32 chars.
        if len(plaintext) > 64:
            continue
        ciphertext = encrypt_totp_secret(plaintext)
        bind.execute(
            sa.text("UPDATE users SET totp_secret = :ct WHERE id = :id"),
            {"ct": ciphertext, "id": row_id},
        )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade is unsupported: existing users.totp_secret values are "
        "Fernet ciphertexts that cannot be silently restored to plaintext. "
        "To downgrade, decrypt every users.totp_secret value manually with "
        "AUTH_TOTP_ENCRYPTION_KEY first, then edit this migration's "
        "downgrade() to drop last_totp_counter and shrink totp_secret to "
        "varchar(64).",
    )
