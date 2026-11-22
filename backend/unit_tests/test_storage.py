"""The object-storage abstraction (ADR-011).

One interface, two backends, chosen from settings by credential completeness. The
filesystem backend is exercised for real against a `tmp_path` directory, because it is
the default and the only one this environment can run. The S3 backend is exercised
through *selection* only: constructing a boto3 client makes no network call, while every
operation does.

Recorded skip: `S3Storage`'s four methods are not executed anywhere in this suite. There
is no S3-compatible service here and the suite must not require network access. What is
covered instead is the key layout — a pure function, and the only part with logic — and
the selection rule from both sides. The residual risk is in the spec's risk table.
"""

import inspect

import pytest

from app.config import get_settings
from app.services.storage import get_storage
from app.services.storage.base import (
    ObjectNotFoundError,
    StorageError,
    build_storage_key,
)
from app.services.storage.filesystem import FilesystemStorage
from app.services.storage.s3 import S3Storage


def test_the_key_is_workspace_and_document_scoped():
    assert build_storage_key("ws-1", "doc-1") == "workspaces/ws-1/files/doc-1"


def test_the_key_takes_no_client_supplied_text():
    """The path-traversal defence is structural, not a sanitiser.

    There is no filename parameter, so a filename of `../../etc/passwd` has nowhere to
    enter the key and the filesystem backend never has to clean one up.
    """
    assert list(inspect.signature(build_storage_key).parameters) == [
        "workspace_id",
        "document_id",
    ]


async def test_filesystem_round_trip(tmp_path):
    storage = FilesystemStorage(tmp_path)

    await storage.upload_file("a/b", b"hello", content_type="text/plain")

    assert await storage.exists("a/b") is True
    assert await storage.download_file("a/b") == b"hello"

    await storage.delete_file("a/b")

    assert await storage.exists("a/b") is False


async def test_filesystem_delete_is_idempotent(tmp_path):
    """A retried delete must not raise: the delete paths call this best-effort."""
    storage = FilesystemStorage(tmp_path)
    await storage.upload_file("k", b"x", content_type="text/plain")
    await storage.delete_file("k")
    await storage.delete_file("k")


async def test_filesystem_download_of_an_unknown_key_raises(tmp_path):
    storage = FilesystemStorage(tmp_path)
    with pytest.raises(ObjectNotFoundError):
        await storage.download_file("missing")


async def test_filesystem_refuses_a_key_that_escapes_its_root(tmp_path):
    """Cannot fire today — `build_storage_key` takes no client input.

    It is here because for a filesystem backend a bad key is an arbitrary file write,
    which is worth one comparison to prevent.
    """
    storage = FilesystemStorage(tmp_path / "root")
    with pytest.raises(StorageError):
        await storage.upload_file("../escape", b"x", content_type="text/plain")


def test_the_filesystem_backend_names_itself(tmp_path):
    assert FilesystemStorage(tmp_path).name == "filesystem"


def test_the_filesystem_is_chosen_when_nothing_is_configured(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_S3_BUCKET", "")
    monkeypatch.setattr(settings, "STORAGE_S3_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "STORAGE_S3_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))

    assert isinstance(get_storage(), FilesystemStorage)


def test_object_storage_is_chosen_when_credentials_are_configured(monkeypatch):
    """No network access: constructing a boto3 client makes no request.

    The first operation makes the first request, and this test performs none.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_S3_BUCKET", "mokinjay-test")
    monkeypatch.setattr(settings, "STORAGE_S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "STORAGE_S3_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "STORAGE_S3_SECRET_ACCESS_KEY", "test-secret")

    storage = get_storage()

    assert isinstance(storage, S3Storage)
    assert storage.bucket == "mokinjay-test"
    assert storage.name == "s3"


def test_a_partial_credential_set_falls_back_to_the_filesystem(monkeypatch, tmp_path):
    """A bucket with no keys cannot work, so it must not be able to select itself."""
    settings = get_settings()
    monkeypatch.setattr(settings, "STORAGE_S3_BUCKET", "mokinjay-test")
    monkeypatch.setattr(settings, "STORAGE_S3_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "STORAGE_S3_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))

    assert isinstance(get_storage(), FilesystemStorage)


def _clear_storage_settings(monkeypatch, settings, tmp_path):
    for name in (
        "STORAGE_S3_BUCKET", "STORAGE_S3_ENDPOINT_URL", "STORAGE_S3_ACCESS_KEY_ID",
        "STORAGE_S3_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
        "AWS_ENDPOINT_URL_S3", "AWS_REGION",
    ):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))


def test_neon_aws_variables_fill_in_missing_storage_settings(monkeypatch, tmp_path):
    """`neon env pull` writes AWS-standard names; a bucket name selects them."""
    settings = get_settings()
    _clear_storage_settings(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(settings, "STORAGE_S3_BUCKET", "assets")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "neon-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "neon-secret")
    monkeypatch.setattr(settings, "AWS_ENDPOINT_URL_S3", "https://br-x.storage.c-9.us-east-2.aws.neon.tech")
    monkeypatch.setattr(settings, "AWS_REGION", "us-east-2")

    storage = get_storage()

    assert isinstance(storage, S3Storage)
    assert storage.bucket == "assets"
    assert storage._client.meta.endpoint_url == "https://br-x.storage.c-9.us-east-2.aws.neon.tech"
    assert storage._client.meta.region_name == "us-east-2"


def test_explicit_storage_settings_win_over_aws_variables(monkeypatch, tmp_path):
    settings = get_settings()
    _clear_storage_settings(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(settings, "STORAGE_S3_BUCKET", "b2-bucket")
    monkeypatch.setattr(settings, "STORAGE_S3_ENDPOINT_URL", "https://s3.us-west-004.backblazeb2.com")
    monkeypatch.setattr(settings, "STORAGE_S3_ACCESS_KEY_ID", "b2-key")
    monkeypatch.setattr(settings, "STORAGE_S3_SECRET_ACCESS_KEY", "b2-secret")
    monkeypatch.setattr(settings, "AWS_ENDPOINT_URL_S3", "https://neon.example")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "neon-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "neon-secret")

    storage = get_storage()

    assert storage._client.meta.endpoint_url == "https://s3.us-west-004.backblazeb2.com"


def test_aws_keys_without_a_bucket_name_stay_on_the_filesystem(monkeypatch, tmp_path):
    settings = get_settings()
    _clear_storage_settings(monkeypatch, settings, tmp_path)
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "neon-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "neon-secret")

    assert isinstance(get_storage(), FilesystemStorage)


def test_the_s3_client_uses_path_style_addressing():
    """Neon Object Storage requires path-style; B2 and MinIO accept it too."""
    storage = S3Storage(
        bucket="assets", endpoint_url="https://neon.example", region="us-east-2",
        access_key_id="k", secret_access_key="s",
    )
    assert storage._client.meta.config.s3["addressing_style"] == "path"
