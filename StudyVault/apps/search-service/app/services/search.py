from __future__ import annotations

from typing import Literal

from studyvault_backend_common.logging import get_logger
from studyvault_backend_common.models import AuthenticatedUser, DriveItem, FileRecord

from app.repositories.search import SearchRepository


logger = get_logger(__name__)
MAX_SEARCH_QUERY_LENGTH = 100


class SearchService:
    def __init__(self, repository: SearchRepository) -> None:
        self.repository = repository

    def index_item(self, item: DriveItem) -> DriveItem:
        indexed = self.repository.index_item(item)
        logger.info(
            "search document indexed",
            event_name="search_document_indexed",
            event_category="search",
            item_id=item.item_id,
            item_kind=item.kind,
            owner_id=item.owner_id,
            item_name=item.name,
            status="succeeded",
        )
        return indexed

    def index_file(self, file_record: FileRecord) -> FileRecord:
        self.index_item(DriveItem.from_file(file_record))
        return file_record

    def delete_item(self, item_id: str) -> None:
        self.repository.delete_item(item_id)
        logger.info(
            "search document deleted",
            event_name="search_document_deleted",
            event_category="search",
            item_id=item_id,
            status="succeeded",
        )

    def search(
        self,
        user: AuthenticatedUser,
        query: str,
        *,
        include_trashed: bool = False,
        kind: Literal["file", "folder", "all"] = "all",
        parent_id: str | None = None,
    ) -> list[DriveItem]:
        if not query.strip():
            return []
        normalized_query = query.strip()
        results = self.repository.search(
            user.subject,
            normalized_query,
            include_trashed=include_trashed,
            kind=kind,
            parent_id=parent_id,
        )
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
            kind=kind,
            parent_id=parent_id,
            result_count=len(results),
            status="succeeded",
        )
        return results
