from __future__ import annotations

from fastapi import HTTPException, status

from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.repositories.catalog import CatalogRepository


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def create_file(self, file_record: FileRecord) -> FileRecord:
        return self.repository.create_file(file_record)

    def list_user_files(self, user: AuthenticatedUser) -> list[FileRecord]:
        return self.repository.list_files(user.subject)

    def get_user_file(self, user: AuthenticatedUser, file_id: str) -> FileRecord:
        record = self.repository.get_file(user.subject, file_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        return record
