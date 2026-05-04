"""Object-storage helpers (S3-compatible).

The blog feature stores user-uploaded media in an S3 bucket — locally
emulated by LocalStack via ``compose.yml``, real AWS S3 in production.
This package isolates the boto3/aioboto3 surface so the rest of the app
sees a small async interface.
"""
