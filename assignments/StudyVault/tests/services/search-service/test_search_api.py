import re

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
