"""Generate an RSA-2048 keypair for JWT RS256 signing.

Usage:
    uv run python scripts/generate_jwt_keys.py [output_dir]

Defaults to ./keys/. Creates jwt_private.pem and jwt_public.pem.
The keys directory is gitignored — do NOT commit generated keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair(output_dir: Path, *, key_size: int = 2048) -> tuple[Path, Path]:
    """Generate an RSA keypair and write the PEMs to ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path = output_dir / "jwt_private.pem"
    public_path = output_dir / "jwt_public.pem"

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    private_path.chmod(0o600)

    return private_path, public_path


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./keys")
    private_path, public_path = generate_rsa_keypair(output_dir)
    print(f"Generated:\n  {private_path}\n  {public_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
