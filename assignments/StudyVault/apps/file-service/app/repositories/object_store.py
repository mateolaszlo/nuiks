from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import boto3

from studyvault_backend_common.models import FileRecord


class ObjectStoreRepository(Protocol):
    def store(self, file_record: FileRecord, content: bytes) -> None: ...

    def get(self, object_key: str) -> bytes: ...

    def ping(self) -> None: ...


class InMemoryObjectStoreRepository:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def store(self, file_record: FileRecord, content: bytes) -> None:
        self._objects[file_record.object_key] = content

    def get(self, object_key: str) -> bytes:
        return self._objects[object_key]

    def ping(self) -> None:
        return None


class S3ObjectStoreRepository:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        region_name: str,
    ) -> None:
        self.bucket_name = bucket_name
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )

    def ensure_bucket(self) -> None:
        existing = self.client.list_buckets().get("Buckets", [])
        if not any(bucket["Name"] == self.bucket_name for bucket in existing):
            self.client.create_bucket(Bucket=self.bucket_name)

    def ping(self) -> None:
        self.client.list_buckets()

    def store(self, file_record: FileRecord, content: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=file_record.object_key,
            Body=content,
            ContentType=file_record.mime_type,
        )

    def get(self, object_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)
        return response["Body"].read()
