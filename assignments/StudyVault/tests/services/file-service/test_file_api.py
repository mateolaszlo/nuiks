from __future__ import annotations

from fastapi.testclient import TestClient

from studyvault_backend_common.models import FileRecord
from tests.conftest import load_service_module


class FakeDownstream:
    def __init__(self) -> None:
        self.catalog_records: list[FileRecord] = []
        self.search_records: list[FileRecord] = []
        self.activity_file_ids: list[str] = []

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.catalog_records.append(file_record)

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.search_records.append(file_record)

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        self.activity_file_ids.append(event.file.file_id)

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        for record in self.catalog_records:
            if record.file_id == file_id:
                return record
        raise AssertionError("expected file to be present in fake downstream catalog store")


def test_file_upload_fans_out_to_all_downstream_services() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"tags": "math"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "lecture.txt"
    assert payload["tags"] == ["math"]
    assert len(downstream.catalog_records) == 1
    assert len(downstream.search_records) == 1
    assert downstream.activity_file_ids == [payload["file_id"]]


def test_file_upload_rejects_empty_content() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_oversize_content() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream, max_upload_bytes=100)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("large.txt", b"x" * 101, "text/plain")},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file exceeds the maximum allowed size"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_filename_with_path_separator() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("nested/lecture.txt", b"hello studyvault", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Filename must not contain path separators"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_filename_longer_than_maximum() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)
    long_filename = f"{'a' * 256}.txt"

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": (long_filename, b"hello studyvault", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Filename must be at most 255 characters"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_too_many_tags() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)
    multipart_payload = [("file", ("lecture.txt", b"hello studyvault", "text/plain"))]
    multipart_payload.extend(("tags", (None, f"tag-{index}")) for index in range(21))

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files=multipart_payload,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Tags must contain at most 20 items"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_upload_rejects_overlong_tag() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
            data={"tags": "x" * 65},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Tags must be at most 64 characters"
    assert downstream.catalog_records == []
    assert downstream.search_records == []
    assert downstream.activity_file_ids == []
    assert object_store._objects == {}


def test_file_download_streams_content_from_object_store() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("lecture.txt", b"hello studyvault", "text/plain")},
        )
        file_id = upload_response.json()["file_id"]
        download_response = client.get(
            f"/api/files/{file_id}/download",
            headers={"authorization": "Bearer fake"},
        )

    assert download_response.status_code == 200
    assert download_response.content == b"hello studyvault"
    assert download_response.headers["content-type"].startswith("text/plain")
    assert (
        download_response.headers["content-disposition"]
        == 'attachment; filename="lecture.txt"; filename*=UTF-8\'\'lecture.txt'
    )


def test_file_download_sanitizes_unsafe_filename_in_content_disposition() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    legacy_record = FileRecord.model_construct(
        file_id="legacy-file",
        owner_id="test-user",
        filename='bad"\r\nname.txt',
        mime_type="text/plain",
        size=len(b"hello studyvault"),
        tags=[],
        object_key="test-user/legacy-file",
    )

    class LegacyDownstream(FakeDownstream):
        async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
            return legacy_record

    downstream = LegacyDownstream()
    object_store._objects[legacy_record.object_key] = b"hello studyvault"
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        download_response = client.get(
            "/api/files/legacy-file/download",
            headers={"authorization": "Bearer fake"},
        )

    header = download_response.headers["content-disposition"]
    assert download_response.status_code == 200
    assert "\r" not in header
    assert "\n" not in header
    assert 'filename="badname.txt"' in header
    assert "filename*=UTF-8''badname.txt" in header


def test_file_download_emits_encoded_filename_for_non_ascii_name() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("žetón notes.pdf", b"hello studyvault", "application/pdf")},
        )
        file_id = upload_response.json()["file_id"]
        download_response = client.get(
            f"/api/files/{file_id}/download",
            headers={"authorization": "Bearer fake"},
        )

    header = download_response.headers["content-disposition"]
    assert download_response.status_code == 200
    assert 'filename="zeton notes.pdf"' in header
    assert "filename*=UTF-8''%C5%BEet%C3%B3n%20notes.pdf" in header
