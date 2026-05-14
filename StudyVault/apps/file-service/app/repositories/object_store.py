from __future__ import annotations

from collections.abc import Iterable
from typing import BinaryIO, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from studyvault_backend_common.models import FileRecord


class ObjectStoreNotFoundError(FileNotFoundError):
    """Raised when an object key does not exist in storage."""


class ObjectStoreUnavailableError(RuntimeError):
    """Raised when the backing object store cannot serve a request."""


class ObjectStoreRepository(Protocol):
    def store(self, file_record: FileRecord, stream: BinaryIO, size: int) -> None: ...

    def get(self, object_key: str) -> bytes: ...

    def delete(self, object_key: str) -> None: ...

    def ping(self) -> None: ...


class InMemoryObjectStoreRepository:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def store(self, file_record: FileRecord, stream: BinaryIO, size: int) -> None:
        self._objects[file_record.object_key] = stream.read(size)

    def get(self, object_key: str) -> bytes:
        try:
            return self._objects[object_key]
        except KeyError as exc:
            raise ObjectStoreNotFoundError(object_key) from exc

    def delete(self, object_key: str) -> None:
        try:
            del self._objects[object_key]
        except KeyError as exc:
            raise ObjectStoreNotFoundError(object_key) from exc

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

    @staticmethod
    def _is_missing_bucket_error(exc: ClientError) -> bool:
        error_code = exc.response.get("Error", {}).get("Code")
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return error_code in {"404", "NoSuchBucket", "NotFound"} or status_code == 404

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as exc:
            if self._is_missing_bucket_error(exc):
                try:
                    self.client.create_bucket(Bucket=self.bucket_name)
                    self.client.head_bucket(Bucket=self.bucket_name)
                    return
                except ClientError as create_exc:
                    raise ObjectStoreUnavailableError(
                        f"Configured object bucket {self.bucket_name} is not accessible"
                    ) from create_exc
                except BotoCoreError as create_exc:
                    raise ObjectStoreUnavailableError(
                        f"Configured object bucket {self.bucket_name} is not accessible"
                    ) from create_exc
            raise ObjectStoreUnavailableError(
                f"Configured object bucket {self.bucket_name} is not accessible"
            ) from exc
        except BotoCoreError as exc:
            raise ObjectStoreUnavailableError(
                f"Configured object bucket {self.bucket_name} is not accessible"
            ) from exc

    def ping(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as exc:
            if self._is_missing_bucket_error(exc):
                return
            raise ObjectStoreUnavailableError(
                f"Configured object bucket {self.bucket_name} is not accessible"
            ) from exc
        except BotoCoreError as exc:
            raise ObjectStoreUnavailableError(
                f"Configured object bucket {self.bucket_name} is not accessible"
            ) from exc

    def store(self, file_record: FileRecord, stream: BinaryIO, size: int) -> None:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=file_record.object_key,
            Body=stream,
            ContentLength=size,
            ContentType=file_record.mime_type,
        )

    def get(self, object_key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStoreNotFoundError(object_key) from exc
            raise ObjectStoreUnavailableError(f"Failed to fetch object {object_key}") from exc
        except BotoCoreError as exc:
            raise ObjectStoreUnavailableError(f"Failed to fetch object {object_key}") from exc
        return response["Body"].read()

    def delete(self, object_key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectStoreNotFoundError(object_key) from exc
            raise ObjectStoreUnavailableError(f"Failed to delete object {object_key}") from exc
        except BotoCoreError as exc:
            raise ObjectStoreUnavailableError(f"Failed to delete object {object_key}") from exc
