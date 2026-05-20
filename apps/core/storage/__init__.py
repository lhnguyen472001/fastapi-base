"""Object-storage helpers (S3-compatible).

The blog feature stores user-uploaded media in an S3 bucket — locally
emulated by LocalStack via ``compose.yml``, real AWS S3 in production.
This package isolates the boto3/aioboto3 surface so the rest of the app
sees a small async interface — :class:`StorageAdapterProtocol`.

Concrete implementation:

* :class:`apps.core.storage.s3.S3Client` — async aioboto3 client used in
  production and integration tests against LocalStack.

Test doubles satisfy the protocol structurally (no inheritance needed),
which is why MED-4 swapped the service-side annotations from the
concrete class to the protocol.
"""

from __future__ import annotations

from .protocol import StorageAdapterProtocol

__all__ = ["StorageAdapterProtocol"]
