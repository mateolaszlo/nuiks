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
