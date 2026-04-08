from datetime import datetime, timezone

import pytest

from studyvault_backend_common.models import (
    BreadcrumbEntry,
    CreateFolderRequest,
    DriveItem,
    FileRecord,
    FolderRecord,
    MoveItemRequest,
    RenameItemRequest,
    RestoreItemRequest,
    normalize_item_name,
    validate_item_name,
)


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
    assert record.parent_folder_id is None
    assert record.trashed_at is None
    assert record.purge_after is None
    assert record.original_parent_folder_id is None
    assert record.updated_at.tzinfo == timezone.utc


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


def test_validate_item_name_normalizes_whitespace() -> None:
    assert validate_item_name("  Semester Notes  ", field_name="Name") == "Semester Notes"


def test_validate_item_name_rejects_control_characters() -> None:
    with pytest.raises(ValueError, match="control characters"):
        validate_item_name("bad\x00name", field_name="Folder name")


def test_normalize_item_name_is_casefolded() -> None:
    assert normalize_item_name("  Data SCIENCE  ") == "data science"


def test_folder_record_create_sets_normalized_name() -> None:
    folder = FolderRecord.create(
        owner_id="user-123",
        name="Course Notes",
        parent_folder_id="root-folder",
        path_depth=1,
    )

    assert folder.owner_id == "user-123"
    assert folder.name == "Course Notes"
    assert folder.normalized_name == "course notes"
    assert folder.parent_folder_id == "root-folder"
    assert folder.path_depth == 1
    assert folder.deleted_by_cascade is False
    assert folder.trashed_at is None


def test_folder_record_rejects_path_separator() -> None:
    with pytest.raises(ValueError, match="path separators"):
        FolderRecord.create(owner_id="user-123", name="Unit/One")


def test_drive_item_from_file_preserves_drive_metadata() -> None:
    trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    purge_after = datetime(2026, 5, 8, tzinfo=timezone.utc)
    record = FileRecord(
        file_id="file-1",
        owner_id="user-123",
        filename="summary.md",
        mime_type="text/markdown",
        size=32,
        tags=["revision"],
        object_key="user-123/file-1",
        parent_folder_id="folder-1",
        trashed_at=trashed_at,
        purge_after=purge_after,
        original_parent_folder_id="folder-0",
    )

    item = DriveItem.from_file(record)

    assert item.kind == "file"
    assert item.item_id == "file-1"
    assert item.name == "summary.md"
    assert item.parent_folder_id == "folder-1"
    assert item.trashed_at == trashed_at
    assert item.purge_after == purge_after
    assert item.tags == ["revision"]
    assert item.object_key == "user-123/file-1"


def test_drive_item_from_folder_preserves_folder_metadata() -> None:
    folder = FolderRecord(
        folder_id="folder-1",
        owner_id="user-123",
        name="Projects",
        parent_folder_id=None,
        path_depth=0,
        deleted_by_cascade=True,
    )

    item = DriveItem.from_folder(folder)

    assert item.kind == "folder"
    assert item.item_id == "folder-1"
    assert item.name == "Projects"
    assert item.path_depth == 0
    assert item.deleted_by_cascade is True
    assert item.size is None
    assert item.object_key is None


def test_folder_request_dtos_validate_names() -> None:
    folder_request = CreateFolderRequest(name=" Exams ", parent_folder_id="folder-1")
    rename_request = RenameItemRequest(name=" Archive ")

    assert folder_request.name == "Exams"
    assert rename_request.name == "Archive"


def test_move_and_restore_requests_allow_root_destination() -> None:
    assert MoveItemRequest(parent_folder_id=None).parent_folder_id is None
    assert RestoreItemRequest(parent_folder_id=None).parent_folder_id is None


def test_breadcrumb_entry_keeps_virtual_root_shape() -> None:
    root = BreadcrumbEntry(name="My Drive")

    assert root.folder_id is None
    assert root.name == "My Drive"
