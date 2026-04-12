import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from studyvault_backend_common.models import FileRecord
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
    assert observed_filter["$or"][0]["filename"]["$regex"] == expected_pattern
    assert observed_filter["$or"][1]["mime_type"]["$regex"] == expected_pattern
    assert observed_filter["$or"][2]["tags"]["$regex"] == expected_pattern
    assert observed_filter["$or"][0]["filename"]["$options"] == "i"


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
