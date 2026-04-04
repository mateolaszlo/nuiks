import pytest

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
    assert record.object_key == f"user-123/{record.file_id}"
    assert record.tags == ["math"]


def test_file_record_create_rejects_filename_with_path_separator() -> None:
    with pytest.raises(ValueError, match="path separators"):
        FileRecord.create(
            owner_id="user-123",
            filename="nested/notes.pdf",
            mime_type="application/pdf",
            size=128,
            tags=["math"],
        )


def test_file_record_create_rejects_excessive_tag_count() -> None:
    with pytest.raises(ValueError, match="at most 20 items"):
        FileRecord.create(
            owner_id="user-123",
            filename="notes.pdf",
            mime_type="application/pdf",
            size=128,
            tags=[f"tag-{index}" for index in range(21)],
        )
