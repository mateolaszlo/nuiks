from __future__ import annotations

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import AuthenticatedUser, FileRecord

from app.repositories.search import SearchRepository


logger = get_logger(__name__)
MAX_SEARCH_QUERY_LENGTH = 100


class SearchService:
    def __init__(self, repository: SearchRepository) -> None:
        self.repository = repository

    def index_file(self, file_record: FileRecord) -> FileRecord:
        indexed = self.repository.index_file(file_record)
        logger.info(
            "search document indexed",
            event_name="search_document_indexed",
            event_category="search",
            file_id=file_record.file_id,
            owner_id=file_record.owner_id,
            filename=file_record.filename,
            mime_type=file_record.mime_type,
            tags_count=len(file_record.tags),
            status="succeeded",
        )
        return indexed

    def delete_item(self, item_id: str) -> None:
        self.repository.delete_item(item_id)
        logger.info(
            "search document deleted",
            event_name="search_document_deleted",
            event_category="search",
            item_id=item_id,
            status="succeeded",
        )

    def search(self, user: AuthenticatedUser, query: str, *, include_trashed: bool = False) -> list[FileRecord]:
        if not query.strip():
            return []
        normalized_query = query.strip()
        results = self.repository.search(user.subject, normalized_query, include_trashed=include_trashed)
        logger.info(
            "search executed",
            event_name="search_executed",
            event_category="search",
            owner_id=user.subject,
            owner_username=user.username,
            owner_email=user.email,
            query=normalized_query,
            query_length=len(normalized_query),
            include_trashed=include_trashed,
            result_count=len(results),
            status="succeeded",
        )
        return results
