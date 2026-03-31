from __future__ import annotations

from fastapi.testclient import TestClient

from studyvault_backend_common.models import ActivityRecord, FileRecord
from tests.conftest import load_service_module


class FakeDownstream:
    def __init__(self) -> None:
        self.catalog_records: dict[str, FileRecord] = {}
        self.search_records: dict[str, FileRecord] = {}
        self.activity_records: list[ActivityRecord] = []

    async def publish_catalog(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.catalog_records[file_record.file_id] = file_record

    async def publish_search(self, file_record: FileRecord, *, bearer_token: str) -> None:
        self.search_records[file_record.file_id] = file_record

    async def publish_activity(self, event, *, bearer_token: str) -> None:
        self.activity_records.append(
            ActivityRecord(
                owner_id=event.file.owner_id,
                action=event.action,
                file_id=event.file.file_id,
                filename=event.file.filename,
                created_at=event.file.created_at,
            )
        )

    async def fetch_catalog_file(self, file_id: str, *, bearer_token: str) -> FileRecord:
        return self.catalog_records[file_id]


def test_upload_flow_produces_metadata_search_and_activity_views() -> None:
    module = load_service_module("file")
    object_store = module.InMemoryObjectStoreRepository()
    downstream = FakeDownstream()
    app = module.create_app(object_store=object_store, downstream=downstream)

    with TestClient(app) as client:
        response = client.post(
            "/api/files",
            headers={"authorization": "Bearer fake"},
            files={"file": ("summary.md", b"# summary", "text/markdown")},
            data={"tags": "revision"},
        )

    assert response.status_code == 200
    payload = response.json()
    file_id = payload["file_id"]
    assert file_id in downstream.catalog_records
    assert file_id in downstream.search_records
    assert downstream.activity_records[0].file_id == file_id
    assert object_store.get(downstream.catalog_records[file_id].object_key) == b"# summary"
