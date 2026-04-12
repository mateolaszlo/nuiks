from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import create_engine, desc, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from studyvault_backend_common.models import DriveItem, FileRecord, FolderRecord

from app.models.file_record import Base, FileRow, FolderRow


class CatalogRepository(Protocol):
    def create_file(self, file_record: FileRecord) -> FileRecord: ...

    def list_files(self, owner_id: str) -> list[FileRecord]: ...

    def get_file(self, owner_id: str, file_id: str) -> FileRecord | None: ...

    def delete_file(self, owner_id: str, file_id: str) -> None: ...

    def create_folder(self, folder_record: FolderRecord) -> FolderRecord: ...

    def rename_folder(self, folder_record: FolderRecord) -> FolderRecord: ...

    def update_folder(self, folder_record: FolderRecord) -> FolderRecord: ...

    def get_folder(self, owner_id: str, folder_id: str) -> FolderRecord | None: ...

    def delete_folder(self, owner_id: str, folder_id: str) -> None: ...

    def list_folders(self, owner_id: str) -> list[FolderRecord]: ...

    def list_child_folders(
        self,
        owner_id: str,
        parent_folder_id: str | None,
        *,
        include_trashed: bool = False,
    ) -> list[FolderRecord]: ...

    def list_child_files(self, owner_id: str, parent_folder_id: str | None) -> list[FileRecord]: ...

    def update_file(self, file_record: FileRecord) -> FileRecord: ...

    def list_items(self, owner_id: str, parent_folder_id: str | None) -> list[DriveItem]: ...

    def list_trashed_items(self, owner_id: str) -> list[DriveItem]: ...

    def get_folder_ancestors(self, owner_id: str, folder_id: str) -> list[FolderRecord]: ...

    def list_expired_trashed_files(self, now: datetime) -> list[FileRecord]: ...

    def list_expired_trashed_folders(self, now: datetime) -> list[FolderRecord]: ...

    def ping(self) -> None: ...


class InMemoryCatalogRepository:
    def __init__(
        self,
        seed: Iterable[FileRecord] | None = None,
        folder_seed: Iterable[FolderRecord] | None = None,
    ) -> None:
        self._records = {record.file_id: record for record in seed or []}
        self._folders = {record.folder_id: record for record in folder_seed or []}

    def create_file(self, file_record: FileRecord) -> FileRecord:
        self._records[file_record.file_id] = file_record
        return file_record

    def list_files(self, owner_id: str) -> list[FileRecord]:
        records = [record for record in self._records.values() if record.owner_id == owner_id]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def get_file(self, owner_id: str, file_id: str) -> FileRecord | None:
        record = self._records.get(file_id)
        if record and record.owner_id == owner_id:
            return record
        return None

    def delete_file(self, owner_id: str, file_id: str) -> None:
        record = self.get_file(owner_id, file_id)
        if record is not None:
            del self._records[file_id]

    def create_folder(self, folder_record: FolderRecord) -> FolderRecord:
        self._folders[folder_record.folder_id] = folder_record
        return folder_record

    def rename_folder(self, folder_record: FolderRecord) -> FolderRecord:
        self._folders[folder_record.folder_id] = folder_record
        return folder_record

    def update_folder(self, folder_record: FolderRecord) -> FolderRecord:
        self._folders[folder_record.folder_id] = folder_record
        return folder_record

    def get_folder(self, owner_id: str, folder_id: str) -> FolderRecord | None:
        record = self._folders.get(folder_id)
        if record and record.owner_id == owner_id:
            return record
        return None

    def delete_folder(self, owner_id: str, folder_id: str) -> None:
        record = self.get_folder(owner_id, folder_id)
        if record is not None:
            del self._folders[folder_id]

    def list_folders(self, owner_id: str) -> list[FolderRecord]:
        records = [record for record in self._folders.values() if record.owner_id == owner_id]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def list_child_folders(
        self,
        owner_id: str,
        parent_folder_id: str | None,
        *,
        include_trashed: bool = False,
    ) -> list[FolderRecord]:
        records = [
            record
            for record in self._folders.values()
            if record.owner_id == owner_id
            and record.parent_folder_id == parent_folder_id
            and (include_trashed or record.trashed_at is None)
        ]
        return sorted(records, key=lambda item: (item.normalized_name or item.name.casefold(), item.created_at))

    def list_child_files(self, owner_id: str, parent_folder_id: str | None) -> list[FileRecord]:
        records = [
            record
            for record in self._records.values()
            if record.owner_id == owner_id and record.parent_folder_id == parent_folder_id
        ]
        return sorted(records, key=lambda item: (item.filename.casefold(), item.created_at, item.file_id))

    def update_file(self, file_record: FileRecord) -> FileRecord:
        self._records[file_record.file_id] = file_record
        return file_record

    def list_items(self, owner_id: str, parent_folder_id: str | None) -> list[DriveItem]:
        folders = [
            DriveItem.from_folder(record)
            for record in self._folders.values()
            if record.owner_id == owner_id
            and record.parent_folder_id == parent_folder_id
            and record.trashed_at is None
        ]
        files = [
            DriveItem.from_file(record)
            for record in self._records.values()
            if record.owner_id == owner_id
            and record.parent_folder_id == parent_folder_id
            and record.trashed_at is None
        ]
        return sorted(folders + files, key=self._drive_item_sort_key)

    def list_trashed_items(self, owner_id: str) -> list[DriveItem]:
        folders = [
            DriveItem.from_folder(record)
            for record in self._folders.values()
            if record.owner_id == owner_id and record.trashed_at is not None
        ]
        files = [
            DriveItem.from_file(record)
            for record in self._records.values()
            if record.owner_id == owner_id and record.trashed_at is not None
        ]
        return sorted(folders + files, key=self._trashed_item_sort_key)

    def get_folder_ancestors(self, owner_id: str, folder_id: str) -> list[FolderRecord]:
        ancestors: list[FolderRecord] = []
        current = self.get_folder(owner_id, folder_id)
        while current is not None and current.parent_folder_id is not None:
            parent = self.get_folder(owner_id, current.parent_folder_id)
            if parent is None:
                break
            ancestors.append(parent)
            current = parent
        ancestors.reverse()
        return ancestors

    def list_expired_trashed_files(self, now: datetime) -> list[FileRecord]:
        expired = [
            record
            for record in self._records.values()
            if record.trashed_at is not None and record.purge_after is not None and record.purge_after <= now
        ]
        return sorted(expired, key=lambda item: (item.purge_after, item.created_at, item.file_id))

    def list_expired_trashed_folders(self, now: datetime) -> list[FolderRecord]:
        expired = [
            record
            for record in self._folders.values()
            if record.trashed_at is not None and record.purge_after is not None and record.purge_after <= now
        ]
        return sorted(expired, key=lambda item: (item.purge_after, item.created_at, item.folder_id))

    def ping(self) -> None:
        return None

    @staticmethod
    def _drive_item_sort_key(item: DriveItem) -> tuple[int, str, datetime, str]:
        return (0 if item.kind == "folder" else 1, item.name.casefold(), item.created_at, item.item_id)

    @staticmethod
    def _trashed_item_sort_key(item: DriveItem) -> tuple[datetime, int, str, str]:
        trashed_at = item.trashed_at or item.created_at
        return (trashed_at, 0 if item.kind == "folder" else 1, item.name.casefold(), item.item_id)


class SqlAlchemyCatalogRepository:
    def __init__(self, database_url: str) -> None:
        engine_kwargs = {"future": True}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            engine_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(database_url, **engine_kwargs)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def create_file(self, file_record: FileRecord) -> FileRecord:
        with self.session_factory() as session:
            row = FileRow(
                file_id=file_record.file_id,
                owner_id=file_record.owner_id,
                filename=file_record.filename,
                mime_type=file_record.mime_type,
                size=file_record.size,
                object_key=file_record.object_key,
                tags=json.dumps(file_record.tags),
                created_at=file_record.created_at,
                updated_at=file_record.updated_at,
                parent_folder_id=file_record.parent_folder_id,
                trashed_at=file_record.trashed_at,
                purge_after=file_record.purge_after,
                original_parent_folder_id=file_record.original_parent_folder_id,
            )
            session.add(row)
            self._commit(session)
        return file_record

    def list_files(self, owner_id: str) -> list[FileRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(FileRow).where(FileRow.owner_id == owner_id).order_by(desc(FileRow.created_at))
            ).all()
        return [self._to_record(row) for row in rows]

    def get_file(self, owner_id: str, file_id: str) -> FileRecord | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(FileRow).where(FileRow.owner_id == owner_id, FileRow.file_id == file_id)
            )
        return self._to_record(row) if row else None

    def delete_file(self, owner_id: str, file_id: str) -> None:
        with self.session_factory() as session:
            row = session.scalar(
                select(FileRow).where(FileRow.owner_id == owner_id, FileRow.file_id == file_id)
            )
            if row is None:
                return
            session.delete(row)
            self._commit(session)

    def create_folder(self, folder_record: FolderRecord) -> FolderRecord:
        with self.session_factory() as session:
            row = FolderRow(
                folder_id=folder_record.folder_id,
                owner_id=folder_record.owner_id,
                name=folder_record.name,
                normalized_name=folder_record.normalized_name or folder_record.name.casefold(),
                parent_folder_id=folder_record.parent_folder_id,
                path_depth=folder_record.path_depth,
                created_at=folder_record.created_at,
                updated_at=folder_record.updated_at,
                trashed_at=folder_record.trashed_at,
                purge_after=folder_record.purge_after,
                original_parent_folder_id=folder_record.original_parent_folder_id,
                deleted_by_cascade=folder_record.deleted_by_cascade,
            )
            session.add(row)
            self._commit(session)
        return folder_record

    def rename_folder(self, folder_record: FolderRecord) -> FolderRecord:
        with self.session_factory() as session:
            row = session.scalar(
                select(FolderRow).where(
                    FolderRow.owner_id == folder_record.owner_id,
                    FolderRow.folder_id == folder_record.folder_id,
                )
            )
            if row is None:
                raise LookupError(f"Folder {folder_record.folder_id} not found")
            row.name = folder_record.name
            row.normalized_name = folder_record.normalized_name or folder_record.name.casefold()
            row.updated_at = folder_record.updated_at
            self._commit(session)
        return folder_record

    def update_folder(self, folder_record: FolderRecord) -> FolderRecord:
        with self.session_factory() as session:
            row = session.scalar(
                select(FolderRow).where(
                    FolderRow.owner_id == folder_record.owner_id,
                    FolderRow.folder_id == folder_record.folder_id,
                )
            )
            if row is None:
                raise LookupError(f"Folder {folder_record.folder_id} not found")
            row.name = folder_record.name
            row.normalized_name = folder_record.normalized_name or folder_record.name.casefold()
            row.parent_folder_id = folder_record.parent_folder_id
            row.path_depth = folder_record.path_depth
            row.updated_at = folder_record.updated_at
            row.trashed_at = folder_record.trashed_at
            row.purge_after = folder_record.purge_after
            row.original_parent_folder_id = folder_record.original_parent_folder_id
            row.deleted_by_cascade = folder_record.deleted_by_cascade
            self._commit(session)
        return folder_record

    def get_folder(self, owner_id: str, folder_id: str) -> FolderRecord | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(FolderRow).where(FolderRow.owner_id == owner_id, FolderRow.folder_id == folder_id)
            )
        return self._to_folder_record(row) if row else None

    def delete_folder(self, owner_id: str, folder_id: str) -> None:
        with self.session_factory() as session:
            row = session.scalar(
                select(FolderRow).where(FolderRow.owner_id == owner_id, FolderRow.folder_id == folder_id)
            )
            if row is None:
                return
            session.delete(row)
            self._commit(session)

    def list_folders(self, owner_id: str) -> list[FolderRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(FolderRow).where(FolderRow.owner_id == owner_id).order_by(desc(FolderRow.created_at))
            ).all()
        return [self._to_folder_record(row) for row in rows]

    def list_child_folders(
        self,
        owner_id: str,
        parent_folder_id: str | None,
        *,
        include_trashed: bool = False,
    ) -> list[FolderRecord]:
        with self.session_factory() as session:
            statement = (
                select(FolderRow)
                .where(
                    FolderRow.owner_id == owner_id,
                    FolderRow.parent_folder_id == parent_folder_id,
                )
                .order_by(FolderRow.normalized_name, FolderRow.created_at, FolderRow.folder_id)
            )
            if not include_trashed:
                statement = statement.where(FolderRow.trashed_at.is_(None))
            rows = session.scalars(statement).all()
        return [self._to_folder_record(row) for row in rows]

    def list_child_files(self, owner_id: str, parent_folder_id: str | None) -> list[FileRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(FileRow)
                .where(
                    FileRow.owner_id == owner_id,
                    FileRow.parent_folder_id == parent_folder_id,
                )
                .order_by(FileRow.filename, FileRow.created_at, FileRow.file_id)
            ).all()
        return [self._to_record(row) for row in rows]

    def update_file(self, file_record: FileRecord) -> FileRecord:
        with self.session_factory() as session:
            row = session.scalar(
                select(FileRow).where(
                    FileRow.owner_id == file_record.owner_id,
                    FileRow.file_id == file_record.file_id,
                )
            )
            if row is None:
                raise LookupError(f"File {file_record.file_id} not found")
            row.filename = file_record.filename
            row.mime_type = file_record.mime_type
            row.size = file_record.size
            row.object_key = file_record.object_key
            row.tags = json.dumps(file_record.tags)
            row.updated_at = file_record.updated_at
            row.parent_folder_id = file_record.parent_folder_id
            row.trashed_at = file_record.trashed_at
            row.purge_after = file_record.purge_after
            row.original_parent_folder_id = file_record.original_parent_folder_id
            self._commit(session)
        return file_record

    def list_items(self, owner_id: str, parent_folder_id: str | None) -> list[DriveItem]:
        with self.session_factory() as session:
            folder_rows = session.scalars(
                select(FolderRow).where(
                    FolderRow.owner_id == owner_id,
                    FolderRow.parent_folder_id == parent_folder_id,
                    FolderRow.trashed_at.is_(None),
                )
            ).all()
            file_rows = session.scalars(
                select(FileRow).where(
                    FileRow.owner_id == owner_id,
                    FileRow.parent_folder_id == parent_folder_id,
                    FileRow.trashed_at.is_(None),
                )
            ).all()
        items = [DriveItem.from_folder(self._to_folder_record(row)) for row in folder_rows]
        items.extend(DriveItem.from_file(self._to_record(row)) for row in file_rows)
        return sorted(items, key=self._drive_item_sort_key)

    def list_trashed_items(self, owner_id: str) -> list[DriveItem]:
        with self.session_factory() as session:
            folder_rows = session.scalars(
                select(FolderRow).where(FolderRow.owner_id == owner_id, FolderRow.trashed_at.is_not(None))
            ).all()
            file_rows = session.scalars(
                select(FileRow).where(FileRow.owner_id == owner_id, FileRow.trashed_at.is_not(None))
            ).all()
        items = [DriveItem.from_folder(self._to_folder_record(row)) for row in folder_rows]
        items.extend(DriveItem.from_file(self._to_record(row)) for row in file_rows)
        return sorted(items, key=self._trashed_item_sort_key)

    def get_folder_ancestors(self, owner_id: str, folder_id: str) -> list[FolderRecord]:
        with self.session_factory() as session:
            rows_by_id = {
                row.folder_id: row
                for row in session.scalars(select(FolderRow).where(FolderRow.owner_id == owner_id)).all()
            }

        ancestors: list[FolderRecord] = []
        current = rows_by_id.get(folder_id)
        while current is not None and current.parent_folder_id is not None:
            parent = rows_by_id.get(current.parent_folder_id)
            if parent is None:
                break
            ancestors.append(self._to_folder_record(parent))
            current = parent
        ancestors.reverse()
        return ancestors

    def list_expired_trashed_files(self, now: datetime) -> list[FileRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(FileRow)
                .where(
                    FileRow.trashed_at.is_not(None),
                    FileRow.purge_after.is_not(None),
                    FileRow.purge_after <= now,
                )
                .order_by(FileRow.purge_after, FileRow.created_at, FileRow.file_id)
            ).all()
        return [self._to_record(row) for row in rows]

    def list_expired_trashed_folders(self, now: datetime) -> list[FolderRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(FolderRow)
                .where(
                    FolderRow.trashed_at.is_not(None),
                    FolderRow.purge_after.is_not(None),
                    FolderRow.purge_after <= now,
                )
                .order_by(FolderRow.purge_after, FolderRow.created_at, FolderRow.folder_id)
            ).all()
        return [self._to_folder_record(row) for row in rows]

    @staticmethod
    def _to_record(row: FileRow) -> FileRecord:
        return FileRecord(
            file_id=row.file_id,
            owner_id=row.owner_id,
            filename=row.filename,
            mime_type=row.mime_type,
            size=row.size,
            object_key=row.object_key,
            tags=json.loads(row.tags or "[]"),
            created_at=SqlAlchemyCatalogRepository._ensure_utc(row.created_at),
            updated_at=SqlAlchemyCatalogRepository._ensure_utc(row.updated_at),
            parent_folder_id=row.parent_folder_id,
            trashed_at=SqlAlchemyCatalogRepository._ensure_utc(row.trashed_at),
            purge_after=SqlAlchemyCatalogRepository._ensure_utc(row.purge_after),
            original_parent_folder_id=row.original_parent_folder_id,
        )

    @staticmethod
    def _to_folder_record(row: FolderRow) -> FolderRecord:
        return FolderRecord(
            folder_id=row.folder_id,
            owner_id=row.owner_id,
            name=row.name,
            normalized_name=row.normalized_name,
            parent_folder_id=row.parent_folder_id,
            path_depth=row.path_depth,
            created_at=SqlAlchemyCatalogRepository._ensure_utc(row.created_at),
            updated_at=SqlAlchemyCatalogRepository._ensure_utc(row.updated_at),
            trashed_at=SqlAlchemyCatalogRepository._ensure_utc(row.trashed_at),
            purge_after=SqlAlchemyCatalogRepository._ensure_utc(row.purge_after),
            original_parent_folder_id=row.original_parent_folder_id,
            deleted_by_cascade=row.deleted_by_cascade,
        )

    @staticmethod
    def _drive_item_sort_key(item: DriveItem) -> tuple[int, str, datetime, str]:
        return (0 if item.kind == "folder" else 1, item.name.casefold(), item.created_at, item.item_id)

    @staticmethod
    def _trashed_item_sort_key(item: DriveItem) -> tuple[datetime, int, str, str]:
        trashed_at = item.trashed_at or item.created_at
        return (trashed_at, 0 if item.kind == "folder" else 1, item.name.casefold(), item.item_id)

    @staticmethod
    def _commit(session) -> None:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise

    @staticmethod
    def _ensure_utc(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)
