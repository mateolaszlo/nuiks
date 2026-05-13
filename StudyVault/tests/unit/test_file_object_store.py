from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from tests.conftest import load_service_module


object_store_module = load_service_module("file", "app.repositories.object_store")
ObjectStoreUnavailableError = object_store_module.ObjectStoreUnavailableError
S3ObjectStoreRepository = object_store_module.S3ObjectStoreRepository


def _head_bucket_client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "failed"}},
        operation_name="HeadBucket",
    )


def test_s3_object_store_ping_uses_bucket_scoped_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeClient:
        def head_bucket(self, *, Bucket: str) -> None:
            calls.append(Bucket)

    monkeypatch.setattr(object_store_module.boto3, "client", lambda *args, **kwargs: FakeClient())

    repository = S3ObjectStoreRepository(
        endpoint_url="http://minio.test:9000",
        access_key="user",
        secret_key="pass",
        bucket_name="studyvault-files",
        region_name="us-east-1",
    )

    repository.ping()

    assert calls == ["studyvault-files"]


def test_s3_object_store_ensure_bucket_requires_existing_accessible_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def head_bucket(self, *, Bucket: str) -> None:
            raise _head_bucket_client_error("403")

    monkeypatch.setattr(object_store_module.boto3, "client", lambda *args, **kwargs: FakeClient())

    repository = S3ObjectStoreRepository(
        endpoint_url="http://minio.test:9000",
        access_key="user",
        secret_key="pass",
        bucket_name="studyvault-files",
        region_name="us-east-1",
    )

    with pytest.raises(ObjectStoreUnavailableError, match="studyvault-files"):
        repository.ensure_bucket()
