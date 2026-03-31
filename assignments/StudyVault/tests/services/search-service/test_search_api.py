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
