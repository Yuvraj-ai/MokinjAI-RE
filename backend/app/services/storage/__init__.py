"""The storage abstraction (ADR-011).

`get_storage()` is the only reader of the storage settings. Object storage when a bucket
and a key pair are configured; the local filesystem otherwise. The interface is a
structural Protocol, so a test double needs no import from this package.
"""

from app.config import get_settings
from app.services.storage.base import (
    ObjectNotFoundError,
    StorageBackend,
    StorageError,
    build_storage_key,
)
from app.services.storage.filesystem import FilesystemStorage
from app.services.storage.s3 import S3Storage

__all__ = [
    "FilesystemStorage",
    "ObjectNotFoundError",
    "S3Storage",
    "StorageBackend",
    "StorageError",
    "build_storage_key",
    "get_storage",
]


def get_storage() -> StorageBackend:
    """The configured backend.

    Credential completeness rather than an explicit switch, so an empty `.env` can only
    ever select the backend that works with an empty `.env` (ADR-011).
    """
    settings = get_settings()
    access_key = settings.STORAGE_S3_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID
    secret_key = settings.STORAGE_S3_SECRET_ACCESS_KEY or settings.AWS_SECRET_ACCESS_KEY
    if settings.STORAGE_S3_BUCKET and access_key and secret_key:
        explicit = settings.STORAGE_S3_ACCESS_KEY_ID and settings.STORAGE_S3_SECRET_ACCESS_KEY
        return S3Storage(
            bucket=settings.STORAGE_S3_BUCKET,
            # An explicit key pair keeps its own endpoint and region, so Neon's
            # AWS_* values never redirect a configured B2/MinIO bucket.
            endpoint_url=settings.STORAGE_S3_ENDPOINT_URL
            or ("" if explicit else settings.AWS_ENDPOINT_URL_S3),
            region=(settings.AWS_REGION if not explicit and settings.AWS_REGION else settings.STORAGE_S3_REGION),
            access_key_id=access_key,
            secret_access_key=secret_key,
        )
    return FilesystemStorage(settings.STORAGE_LOCAL_PATH)
