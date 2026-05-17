from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from studyvault_backend_common.models import AuthenticatedUser, FileRecord, FolderRecord
from tests.conftest import load_service_module


def build_repository():
    module = load_service_module("catalog", "app.repositories.catalog")
    repository = module.SqlAlchemyCatalogRepository("sqlite+pysqlite:///:memory:")
    repository.create_tables()
    return repository


def test_create_tables_bootstraps_files_and_folders() -> None:
    repository = build_repository()

    tables = set(inspect(repository.engine).get_table_names())

    assert tables == {"files", "folders"}


def test_file_metadata_round_trips_drive_fields() -> None:
    repository = build_repository()
    trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    purge_after = trashed_at + timedelta(days=30)
    record = FileRecord(
        file_id="file-1",
        owner_id="user-1",
        filename="Notes.txt",
        mime_type="text/plain",
        size=42,
        tags=["school"],
        object_key="user-1/file-1",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
        parent_folder_id="folder-1",
        trashed_at=trashed_at,
        purge_after=purge_after,
        original_parent_folder_id="folder-0",
    )

    repository.create_file(record)
    stored = repository.get_file("user-1", "file-1")

    assert stored is not None
    assert stored.parent_folder_id == "folder-1"
    assert stored.updated_at == datetime(2026, 4, 2, tzinfo=timezone.utc)
    assert stored.trashed_at == trashed_at
    assert stored.purge_after == purge_after
    assert stored.original_parent_folder_id == "folder-0"


def test_folder_metadata_round_trips_drive_fields() -> None:
    repository = build_repository()
    folder = FolderRecord(
        folder_id="folder-1",
        owner_id="user-1",
        name="Course Notes",
        normalized_name="course notes",
        parent_folder_id=None,
        path_depth=0,
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 3, tzinfo=timezone.utc),
        trashed_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        purge_after=datetime(2026, 5, 8, tzinfo=timezone.utc),
        original_parent_folder_id="archive-1",
        deleted_by_cascade=True,
    )

    repository.create_folder(folder)
    stored = repository.get_folder("user-1", "folder-1")

    assert stored is not None
    assert stored.normalized_name == "course notes"
    assert stored.updated_at == datetime(2026, 4, 3, tzinfo=timezone.utc)
    assert stored.trashed_at == datetime(2026, 4, 8, tzinfo=timezone.utc)
    assert stored.purge_after == datetime(2026, 5, 8, tzinfo=timezone.utc)
    assert stored.deleted_by_cascade is True


def test_active_sibling_folder_names_must_be_unique() -> None:
    repository = build_repository()
    repository.create_folder(
        FolderRecord.create(owner_id="user-1", name="Projects", parent_folder_id=None, path_depth=0)
    )

    with pytest.raises(IntegrityError):
        repository.create_folder(
            FolderRecord.create(owner_id="user-1", name="projects", parent_folder_id=None, path_depth=0)
        )


def test_active_sibling_filenames_must_be_unique() -> None:
    repository = build_repository()
    repository.create_file(
        FileRecord(
            file_id="file-1",
            owner_id="user-1",
            filename="Outline.pdf",
            mime_type="application/pdf",
            size=10,
            tags=[],
            object_key="user-1/file-1",
        )
    )

    with pytest.raises(IntegrityError):
        repository.create_file(
            FileRecord(
                file_id="file-2",
                owner_id="user-1",
                filename="outline.pdf",
                mime_type="application/pdf",
                size=11,
                tags=[],
                object_key="user-1/file-2",
            )
        )


def test_list_items_returns_mixed_active_children_only() -> None:
    repository = build_repository()
    repository.create_folder(
        FolderRecord(
            folder_id="folder-parent",
            owner_id="user-1",
            name="Parent",
            normalized_name="parent",
            path_depth=0,
        )
    )
    repository.create_folder(
        FolderRecord(
            folder_id="folder-active",
            owner_id="user-1",
            name="Alpha",
            normalized_name="alpha",
            parent_folder_id="folder-parent",
            path_depth=1,
        )
    )
    repository.create_folder(
        FolderRecord(
            folder_id="folder-trashed",
            owner_id="user-1",
            name="Hidden",
            normalized_name="hidden",
            parent_folder_id="folder-parent",
            path_depth=1,
            trashed_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        )
    )
    repository.create_file(
        FileRecord(
            file_id="file-active",
            owner_id="user-1",
            filename="beta.txt",
            mime_type="text/plain",
            size=12,
            tags=[],
            object_key="user-1/file-active",
            parent_folder_id="folder-parent",
        )
    )
    repository.create_file(
        FileRecord(
            file_id="file-trashed",
            owner_id="user-1",
            filename="gamma.txt",
            mime_type="text/plain",
            size=13,
            tags=[],
            object_key="user-1/file-trashed",
            parent_folder_id="folder-parent",
            trashed_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
        )
    )

    items = repository.list_items("user-1", "folder-parent")

    assert [(item.kind, item.name) for item in items] == [("folder", "Alpha"), ("file", "beta.txt")]


def test_list_trashed_items_returns_files_and_folders() -> None:
    repository = build_repository()
    repository.create_folder(
        FolderRecord(
            folder_id="folder-1",
            owner_id="user-1",
            name="Folder Trash",
            normalized_name="folder trash",
            path_depth=0,
            trashed_at=datetime(2026, 4, 8, 9, tzinfo=timezone.utc),
            purge_after=datetime(2026, 5, 8, 9, tzinfo=timezone.utc),
        )
    )
    repository.create_file(
        FileRecord(
            file_id="file-1",
            owner_id="user-1",
            filename="File Trash.txt",
            mime_type="text/plain",
            size=1,
            tags=[],
            object_key="user-1/file-1",
            trashed_at=datetime(2026, 4, 8, 10, tzinfo=timezone.utc),
            purge_after=datetime(2026, 5, 8, 10, tzinfo=timezone.utc),
        )
    )

    items = repository.list_trashed_items("user-1")

    assert [(item.kind, item.name) for item in items] == [("folder", "Folder Trash"), ("file", "File Trash.txt")]


def test_get_folder_ancestors_returns_root_to_parent_chain() -> None:
    repository = build_repository()
    repository.create_folder(
        FolderRecord(
            folder_id="root-folder",
            owner_id="user-1",
            name="Root Folder",
            normalized_name="root folder",
            path_depth=0,
        )
    )
    repository.create_folder(
        FolderRecord(
            folder_id="child-folder",
            owner_id="user-1",
            name="Child Folder",
            normalized_name="child folder",
            parent_folder_id="root-folder",
            path_depth=1,
        )
    )
    repository.create_folder(
        FolderRecord(
            folder_id="leaf-folder",
            owner_id="user-1",
            name="Leaf Folder",
            normalized_name="leaf folder",
            parent_folder_id="child-folder",
            path_depth=2,
        )
    )

    ancestors = repository.get_folder_ancestors("user-1", "leaf-folder")

    assert [folder.folder_id for folder in ancestors] == ["root-folder", "child-folder"]


def test_list_expired_trashed_items_filters_by_purge_after() -> None:
    repository = build_repository()
    now = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository.create_folder(
        FolderRecord(
            folder_id="folder-expired",
            owner_id="user-1",
            name="Expired Folder",
            normalized_name="expired folder",
            path_depth=0,
            trashed_at=now - timedelta(days=10),
            purge_after=now - timedelta(minutes=1),
        )
    )
    repository.create_folder(
        FolderRecord(
            folder_id="folder-fresh",
            owner_id="user-1",
            name="Fresh Folder",
            normalized_name="fresh folder",
            path_depth=0,
            trashed_at=now - timedelta(days=1),
            purge_after=now + timedelta(days=1),
        )
    )
    repository.create_file(
        FileRecord(
            file_id="file-expired",
            owner_id="user-1",
            filename="expired.txt",
            mime_type="text/plain",
            size=5,
            tags=[],
            object_key="user-1/file-expired",
            trashed_at=now - timedelta(days=5),
            purge_after=now,
        )
    )
    repository.create_file(
        FileRecord(
            file_id="file-fresh",
            owner_id="user-1",
            filename="fresh.txt",
            mime_type="text/plain",
            size=6,
            tags=[],
            object_key="user-1/file-fresh",
            trashed_at=now - timedelta(days=1),
            purge_after=now + timedelta(hours=1),
        )
    )

    expired_folders = repository.list_expired_trashed_folders(now)
    expired_files = repository.list_expired_trashed_files(now)

    assert [folder.folder_id for folder in expired_folders] == ["folder-expired"]
    assert [file.file_id for file in expired_files] == ["file-expired"]


def test_get_folder_stats_sums_nested_active_descendants() -> None:
    repository = build_repository()
    root = FolderRecord.create(owner_id="user-1", name="Root", path_depth=0)
    child = FolderRecord.create(owner_id="user-1", name="Child", parent_folder_id=root.folder_id, path_depth=1)
    leaf = FolderRecord.create(owner_id="user-1", name="Leaf", parent_folder_id=child.folder_id, path_depth=2)
    repository.create_folder(root)
    repository.create_folder(child)
    repository.create_folder(leaf)
    root_file = FileRecord.create(owner_id="user-1", filename="root.txt", mime_type="text/plain", size=5, tags=[])
    root_file.parent_folder_id = root.folder_id
    child_file = FileRecord.create(owner_id="user-1", filename="child.txt", mime_type="text/plain", size=7, tags=[])
    child_file.parent_folder_id = child.folder_id
    leaf_file = FileRecord.create(owner_id="user-1", filename="leaf.txt", mime_type="text/plain", size=11, tags=[])
    leaf_file.parent_folder_id = leaf.folder_id
    repository.create_file(root_file)
    repository.create_file(child_file)
    repository.create_file(leaf_file)

    stats = repository.get_folder_stats("user-1", root.folder_id)

    assert stats.folder_id == root.folder_id
    assert stats.total_size_bytes == 23
    assert stats.file_count == 3
    assert stats.folder_count == 2


def test_get_folder_stats_excludes_trashed_descendants() -> None:
    repository = build_repository()
    root = FolderRecord.create(owner_id="user-1", name="Root", path_depth=0)
    active_child = FolderRecord.create(owner_id="user-1", name="Active", parent_folder_id=root.folder_id, path_depth=1)
    trashed_child = FolderRecord.create(owner_id="user-1", name="Trashed", parent_folder_id=root.folder_id, path_depth=1)
    trashed_child.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository.create_folder(root)
    repository.create_folder(active_child)
    repository.create_folder(trashed_child)
    active_file = FileRecord.create(owner_id="user-1", filename="keep.txt", mime_type="text/plain", size=4, tags=[])
    active_file.parent_folder_id = active_child.folder_id
    trashed_root_file = FileRecord.create(
        owner_id="user-1",
        filename="ignore-root-trashed.txt",
        mime_type="text/plain",
        size=6,
        tags=[],
    )
    trashed_root_file.parent_folder_id = root.folder_id
    trashed_root_file.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    hidden_file = FileRecord.create(
        owner_id="user-1",
        filename="ignore-trashed-folder.txt",
        mime_type="text/plain",
        size=9,
        tags=[],
    )
    hidden_file.parent_folder_id = trashed_child.folder_id
    repository.create_file(active_file)
    repository.create_file(trashed_root_file)
    repository.create_file(hidden_file)

    stats = repository.get_folder_stats("user-1", root.folder_id)

    assert stats.total_size_bytes == 4
    assert stats.file_count == 1
    assert stats.folder_count == 1


def test_get_folder_stats_returns_zero_for_empty_folder() -> None:
    repository = build_repository()
    root = FolderRecord.create(owner_id="user-1", name="Empty", path_depth=0)
    repository.create_folder(root)

    stats = repository.get_folder_stats("user-1", root.folder_id)

    assert stats.total_size_bytes == 0
    assert stats.file_count == 0
    assert stats.folder_count == 0


def test_catalog_service_get_folder_stats_returns_recursive_totals() -> None:
    repository = build_repository()
    service_module = load_service_module("catalog", "app.services.catalog")
    root = FolderRecord.create(owner_id="user-1", name="Root", path_depth=0)
    child = FolderRecord.create(owner_id="user-1", name="Child", parent_folder_id=root.folder_id, path_depth=1)
    repository.create_folder(root)
    repository.create_folder(child)
    root_file = FileRecord.create(owner_id="user-1", filename="root.txt", mime_type="text/plain", size=2, tags=[])
    root_file.parent_folder_id = root.folder_id
    child_file = FileRecord.create(owner_id="user-1", filename="child.txt", mime_type="text/plain", size=8, tags=[])
    child_file.parent_folder_id = child.folder_id
    repository.create_file(root_file)
    repository.create_file(child_file)
    service = service_module.CatalogService(repository)
    user = AuthenticatedUser(subject="user-1", email="user@example.com", username="user-1", roles=["user"], token="test")

    response = service.get_folder_stats(user, root.folder_id)

    assert response.folder_id == root.folder_id
    assert response.total_size_bytes == 10
    assert response.file_count == 2
    assert response.folder_count == 1


def test_catalog_service_get_folder_stats_rejects_trashed_folder() -> None:
    repository = build_repository()
    service_module = load_service_module("catalog", "app.services.catalog")
    folder = FolderRecord.create(owner_id="user-1", name="Trash", path_depth=0)
    folder.trashed_at = datetime(2026, 4, 8, tzinfo=timezone.utc)
    repository.create_folder(folder)
    service = service_module.CatalogService(repository)
    user = AuthenticatedUser(subject="user-1", email="user@example.com", username="user-1", roles=["user"], token="test")

    with pytest.raises(service_module.HTTPException) as exc_info:
        service.get_folder_stats(user, folder.folder_id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Folder not found"
