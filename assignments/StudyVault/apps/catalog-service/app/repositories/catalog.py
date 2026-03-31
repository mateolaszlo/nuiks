from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import create_engine, desc, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from studyvault_backend_common.models import FileRecord

from app.models.file_record import Base, FileRow


class CatalogRepository(Protocol):
    def create_file(self, file_record: FileRecord) -> FileRecord: ...

    def list_files(self, owner_id: str) -> list[FileRecord]: ...

    def get_file(self, owner_id: str, file_id: str) -> FileRecord | None: ...

    def ping(self) -> None: ...


class InMemoryCatalogRepository:
    def __init__(self, seed: Iterable[FileRecord] | None = None) -> None:
        self._records = {record.file_id: record for record in seed or []}

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

    def ping(self) -> None:
        return None


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
            )
            session.add(row)
            session.commit()
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
            created_at=row.created_at,
        )
