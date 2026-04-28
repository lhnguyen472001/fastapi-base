"""bcrypt password hashing primitives."""

import asyncio

import bcrypt

_BCRYPT_ROUNDS = 12


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt and a fresh salt.

    Synchronous. Safe to call from scripts, seed helpers, and tests.
    In async request paths, prefer :func:`hash_password_async` so the
    bcrypt work (CPU-bound, ~200-500 ms at rounds=12) does not block
    the event loop.
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Synchronous counterpart of :func:`verify_password_async`. Use the
    async version on request paths.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


async def hash_password_async(plain_password: str) -> str:
    """Async wrapper around :func:`hash_password`.

    Runs the CPU-bound bcrypt work on the default thread-pool executor
    so the asyncio event loop stays responsive under concurrent logins
    and registrations.
    """
    return await asyncio.to_thread(hash_password, plain_password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Async wrapper around :func:`verify_password`."""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)
