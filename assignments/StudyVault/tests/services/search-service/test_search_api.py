import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.models import DriveItem, FileRecord, FolderRecord
from tests.conftest import load_service_module


def test_search_matches_filename_and_tag_for_authenticated_user() -> None:
    module = load_service_module("search")
    repository = module.InMemorySearchRepository(
        seed=[
            FileRecord.create(
                owner_id="test-user",
                filename="Linear Algebra Notes.pdf",
                mime_type="application/pdf",
                size=100,
                tags=["math", "revision"],
            ),
            FileRecord.create(
                owner_id="other-user",
                filename="math.txt",
                mime_type="text/plain",
                size=20,
                tags=["math"],
            ),
        ]
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["owner_id"] == "test-user"
    assert payload[0]["filename"] == "Linear Algebra Notes.pdf"


def test_search_repository_stores_drive_items_internally() -> None:
    module = load_service_module("search")
    record = FileRecord.create(
        owner_id="test-user",
        filename="Linear Algebra Notes.pdf",
        mime_type="application/pdf",
        size=100,
        tags=["math"],
    )
    repository = module.InMemorySearchRepository()

    indexed = repository.index_file(record)

    assert indexed == record
    stored = repository._records[record.file_id]
    assert stored.item_id == record.file_id
    assert stored.kind == "file"
    assert stored.name == record.filename


def test_search_skips_folder_items_while_public_api_remains_file_only() -> None:
    module = load_service_module("search")
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="math-notes.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    folder_record = FolderRecord.create(owner_id="test-user", name="Math Folder")
    repository = module.InMemorySearchRepository(seed=[file_record, DriveItem.from_folder(folder_record)])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == file_record.file_id


def test_search_rejects_overlong_query() -> None:
    module = load_service_module("search")
    app = module.create_app(repository=module.InMemorySearchRepository())
    long_query = "a" * 101

    with TestClient(app) as client:
        response = client.get("/api/search", params={"q": long_query}, headers={"authorization": "Bearer fake"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_long"
    assert response.json()["detail"][0]["loc"] == ["query", "q"]


def test_search_returns_empty_list_for_blank_query() -> None:
    module = load_service_module("search")
    app = module.create_app(repository=module.InMemorySearchRepository())

    with TestClient(app) as client:
        response = client.get("/api/search", params={"q": ""}, headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    assert response.json() == []


def test_search_excludes_trashed_files_by_default() -> None:
    module = load_service_module("search")
    active = FileRecord.create(
        owner_id="test-user",
        filename="math-active.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    trashed = FileRecord.create(
        owner_id="test-user",
        filename="math-trashed.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    trashed.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    trashed.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemorySearchRepository(seed=[active, trashed])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert [item["file_id"] for item in payload] == [active.file_id]


def test_search_includes_trashed_files_when_requested() -> None:
    module = load_service_module("search")
    active = FileRecord.create(
        owner_id="test-user",
        filename="math-active.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    trashed = FileRecord.create(
        owner_id="test-user",
        filename="math-trashed.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    trashed.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    trashed.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemorySearchRepository(seed=[active, trashed])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/search?q=math&include_trashed=true",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert {item["file_id"] for item in payload} == {active.file_id, trashed.file_id}


def test_search_include_trashed_still_respects_owner_scope() -> None:
    module = load_service_module("search")
    own_trashed = FileRecord.create(
        owner_id="test-user",
        filename="math-own.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    own_trashed.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    own_trashed.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    other_trashed = FileRecord.create(
        owner_id="other-user",
        filename="math-other.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    other_trashed.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    other_trashed.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemorySearchRepository(seed=[own_trashed, other_trashed])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            "/api/search?q=math&include_trashed=true",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == own_trashed.file_id


def test_search_kind_file_returns_only_matching_files() -> None:
    module = load_service_module("search")
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="math-notes.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    folder_record = FolderRecord.create(owner_id="test-user", name="Math Folder")
    repository = module.InMemorySearchRepository(seed=[file_record, DriveItem.from_folder(folder_record)])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math&kind=file", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == file_record.file_id


def test_search_kind_folder_returns_empty_list_while_public_api_remains_file_only() -> None:
    module = load_service_module("search")
    folder_record = FolderRecord.create(owner_id="test-user", name="Math Folder")
    repository = module.InMemorySearchRepository(seed=[DriveItem.from_folder(folder_record)])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math&kind=folder", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    assert response.json() == []


def test_search_kind_all_still_returns_only_file_records_publicly() -> None:
    module = load_service_module("search")
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="math-notes.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    folder_record = FolderRecord.create(owner_id="test-user", name="Math Folder")
    repository = module.InMemorySearchRepository(seed=[file_record, DriveItem.from_folder(folder_record)])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/search?q=math&kind=all", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == file_record.file_id


def test_search_parent_id_filters_to_direct_parent_folder() -> None:
    module = load_service_module("search")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    other_parent = FolderRecord.create(owner_id="test-user", name="Archive")
    matching = FileRecord.create(
        owner_id="test-user",
        filename="math-notes.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    matching.parent_folder_id = parent.folder_id
    non_matching = FileRecord.create(
        owner_id="test-user",
        filename="math-other.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    non_matching.parent_folder_id = other_parent.folder_id
    repository = module.InMemorySearchRepository(seed=[matching, non_matching])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/search?q=math&parent_id={parent.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == matching.file_id


def test_search_include_trashed_works_with_kind_and_parent_id() -> None:
    module = load_service_module("search")
    parent = FolderRecord.create(owner_id="test-user", name="Projects")
    file_record = FileRecord.create(
        owner_id="test-user",
        filename="math-notes.txt",
        mime_type="text/plain",
        size=20,
        tags=["math"],
    )
    file_record.parent_folder_id = parent.folder_id
    file_record.trashed_at = datetime(2026, 4, 10, tzinfo=timezone.utc)
    file_record.purge_after = datetime(2026, 5, 10, tzinfo=timezone.utc)
    repository = module.InMemorySearchRepository(seed=[file_record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get(
            f"/api/search?q=math&include_trashed=true&kind=file&parent_id={parent.folder_id}",
            headers={"authorization": "Bearer fake"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["file_id"] == file_record.file_id


def test_internal_search_delete_requires_internal_token() -> None:
    module = load_service_module("search")
    record = FileRecord.create(
        owner_id="test-user",
        filename="Linear Algebra Notes.pdf",
        mime_type="application/pdf",
        size=100,
        tags=["math"],
    )
    repository = module.InMemorySearchRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        unauthorized = client.delete(f"/internal/search/items/{record.file_id}")
        authorized = client.delete(
            f"/internal/search/items/{record.file_id}",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 204


def test_internal_search_item_upsert_requires_internal_token() -> None:
    module = load_service_module("search")
    folder = DriveItem.from_folder(FolderRecord.create(owner_id="test-user", name="Projects"))
    app = module.create_app(repository=module.InMemorySearchRepository())

    with TestClient(app) as client:
        unauthorized = client.put(
            f"/internal/search/items/{folder.item_id}",
            json=folder.model_dump(mode="json"),
        )
        authorized = client.put(
            f"/internal/search/items/{folder.item_id}",
            json=folder.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert authorized.json()["item_id"] == folder.item_id
    assert authorized.json()["kind"] == "folder"


def test_internal_search_item_upsert_rejects_item_id_mismatch() -> None:
    module = load_service_module("search")
    folder = DriveItem.from_folder(FolderRecord.create(owner_id="test-user", name="Projects"))
    app = module.create_app(repository=module.InMemorySearchRepository())

    with TestClient(app) as client:
        response = client.put(
            "/internal/search/items/other-id",
            json=folder.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Item id mismatch"


def test_internal_search_item_upsert_stores_folder_document_without_publicly_returning_it() -> None:
    module = load_service_module("search")
    folder = DriveItem.from_folder(FolderRecord.create(owner_id="test-user", name="Projects"))
    repository = module.InMemorySearchRepository()
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        upsert_response = client.put(
            f"/internal/search/items/{folder.item_id}",
            json=folder.model_dump(mode="json"),
            headers={"x-internal-token": "internal-test-token"},
        )
        search_response = client.get("/api/search?q=projects", headers={"authorization": "Bearer fake"})

    assert upsert_response.status_code == 200
    assert repository._records[folder.item_id].kind == "folder"
    assert search_response.status_code == 200
    assert search_response.json() == []


def test_internal_search_delete_removes_item_from_results() -> None:
    module = load_service_module("search")
    record = FileRecord.create(
        owner_id="test-user",
        filename="Linear Algebra Notes.pdf",
        mime_type="application/pdf",
        size=100,
        tags=["math"],
    )
    repository = module.InMemorySearchRepository(seed=[record])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        delete_response = client.delete(
            f"/internal/search/items/{record.file_id}",
            headers={"x-internal-token": "internal-test-token"},
        )
        search_response = client.get("/api/search?q=math", headers={"authorization": "Bearer fake"})

    assert delete_response.status_code == 204
    assert search_response.status_code == 200
    assert search_response.json() == []


def test_internal_search_delete_is_idempotent_for_missing_item() -> None:
    module = load_service_module("search")
    app = module.create_app(repository=module.InMemorySearchRepository())

    with TestClient(app) as client:
        response = client.delete(
            "/internal/search/items/missing-item",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert response.status_code == 204


def test_internal_search_delete_removes_folder_document_idempotently() -> None:
    module = load_service_module("search")
    folder = DriveItem.from_folder(FolderRecord.create(owner_id="test-user", name="Projects"))
    repository = module.InMemorySearchRepository(seed=[folder])
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        first = client.delete(
            f"/internal/search/items/{folder.item_id}",
            headers={"x-internal-token": "internal-test-token"},
        )
        second = client.delete(
            f"/internal/search/items/{folder.item_id}",
            headers={"x-internal-token": "internal-test-token"},
        )

    assert first.status_code == 204
    assert second.status_code == 204
    assert folder.item_id not in repository._records


def test_mongo_search_escapes_regex_metacharacters() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed_filter = {}

    class FakeCursor:
        def sort(self, field: str, direction: int):
            return []

    class FakeCollection:
        def find(self, query):
            observed_filter.update(query)
            return FakeCursor()

    repository.collection = FakeCollection()
    repository.search("test-user", "math.*[notes]")

    expected_pattern = re.escape("math.*[notes]")
    assert observed_filter["owner_id"] == "test-user"
    assert observed_filter["$or"][0]["name"]["$regex"] == expected_pattern
    assert observed_filter["$or"][1]["mime_type"]["$regex"] == expected_pattern
    assert observed_filter["$or"][2]["tags"]["$regex"] == expected_pattern
    assert observed_filter["$or"][0]["name"]["$options"] == "i"


def test_mongo_search_excludes_trashed_files_by_default() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed_filter = {}

    class FakeCursor:
        def sort(self, field: str, direction: int):
            return []

    class FakeCollection:
        def find(self, query):
            observed_filter.update(query)
            return FakeCursor()

    repository.collection = FakeCollection()
    repository.search("test-user", "math")

    assert observed_filter["owner_id"] == "test-user"
    assert observed_filter["trashed_at"] is None


def test_mongo_search_include_trashed_omits_default_filter() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed_filter = {}

    class FakeCursor:
        def sort(self, field: str, direction: int):
            return []

    class FakeCollection:
        def find(self, query):
            observed_filter.update(query)
            return FakeCursor()

    repository.collection = FakeCollection()
    repository.search("test-user", "math", include_trashed=True)

    assert observed_filter["owner_id"] == "test-user"
    assert "trashed_at" not in observed_filter


def test_mongo_search_kind_and_parent_filters_are_applied() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed_filter = {}

    class FakeCursor:
        def sort(self, field: str, direction: int):
            return []

    class FakeCollection:
        def find(self, query):
            observed_filter.update(query)
            return FakeCursor()

    repository.collection = FakeCollection()
    repository.search("test-user", "math", kind="folder", parent_id="folder-1")

    assert observed_filter["owner_id"] == "test-user"
    assert observed_filter["kind"] == "folder"
    assert observed_filter["parent_folder_id"] == "folder-1"
    assert observed_filter["trashed_at"] is None


def test_mongo_search_kind_all_omits_kind_filter() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed_filter = {}

    class FakeCursor:
        def sort(self, field: str, direction: int):
            return []

    class FakeCollection:
        def find(self, query):
            observed_filter.update(query)
            return FakeCursor()

    repository.collection = FakeCollection()
    repository.search("test-user", "math", kind="all")

    assert observed_filter["owner_id"] == "test-user"
    assert "kind" not in observed_filter


def test_mongo_index_file_replaces_drive_item_document() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed = {}
    record = FileRecord.create(
        owner_id="test-user",
        filename="Linear Algebra Notes.pdf",
        mime_type="application/pdf",
        size=100,
        tags=["math"],
    )

    class FakeCollection:
        def replace_one(self, selector, document, upsert=False):
            observed["selector"] = selector
            observed["document"] = document
            observed["upsert"] = upsert

    repository.collection = FakeCollection()
    indexed = repository.index_file(record)

    assert indexed == record
    assert observed["selector"] == {"item_id": record.file_id}
    assert observed["document"]["item_id"] == record.file_id
    assert observed["document"]["kind"] == "file"
    assert observed["document"]["name"] == record.filename
    assert observed["upsert"] is True


def test_mongo_index_item_replaces_folder_drive_item_document() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed = {}
    folder = DriveItem.from_folder(FolderRecord.create(owner_id="test-user", name="Projects"))

    class FakeCollection:
        def replace_one(self, selector, document, upsert=False):
            observed["selector"] = selector
            observed["document"] = document
            observed["upsert"] = upsert

    repository.collection = FakeCollection()
    indexed = repository.index_item(folder)

    assert indexed == folder
    assert observed["selector"] == {"item_id": folder.item_id}
    assert observed["document"]["item_id"] == folder.item_id
    assert observed["document"]["kind"] == "folder"
    assert observed["document"]["name"] == folder.name
    assert observed["upsert"] is True


def test_mongo_delete_item_uses_item_id_selector() -> None:
    module = load_service_module("search")
    repository = module.MongoSearchRepository("mongodb://example.test:27017", "studyvault_search")
    observed = {}

    class FakeCollection:
        def delete_one(self, selector):
            observed["selector"] = selector

    repository.collection = FakeCollection()
    repository.delete_item("item-123")

    assert observed["selector"] == {"item_id": "item-123"}
