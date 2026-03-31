from __future__ import annotations

from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.repositories.search import SearchRepository


class SearchService:
    def __init__(self, repository: SearchRepository) -> None:
        self.repository = repository

    def index_file(self, file_record: FileRecord) -> FileRecord:
        return self.repository.index_file(file_record)

    def search(self, user: AuthenticatedUser, query: str) -> list[FileRecord]:
        if not query.strip():
            return []
        return self.repository.search(user.subject, query.strip())
