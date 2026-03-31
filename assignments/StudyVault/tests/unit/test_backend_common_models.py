from studyvault_backend_common.models import FileRecord


def test_file_record_create_builds_owner_scoped_object_key() -> None:
    record = FileRecord.create(
        owner_id="user-123",
        filename="notes.pdf",
        mime_type="application/pdf",
        size=128,
        tags=["math"],
    )

    assert record.owner_id == "user-123"
    assert record.filename == "notes.pdf"
    assert record.object_key.startswith("user-123/")
    assert record.object_key.endswith("/notes.pdf")
    assert record.tags == ["math"]
