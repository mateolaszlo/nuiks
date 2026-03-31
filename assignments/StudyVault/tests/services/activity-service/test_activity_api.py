from fastapi.testclient import TestClient

from studyvault_backend_common.models import ActivityRecord
from tests.conftest import load_service_module


def test_activity_returns_recent_events_for_user() -> None:
    module = load_service_module("activity")
    repository = module.InMemoryActivityRepository(
        seed=[
            ActivityRecord(owner_id="test-user", action="file_uploaded", file_id="a", filename="a.txt"),
            ActivityRecord(owner_id="other-user", action="file_uploaded", file_id="b", filename="b.txt"),
        ]
    )
    app = module.create_app(repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/activity/me", headers={"authorization": "Bearer fake"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["owner_id"] == "test-user"
