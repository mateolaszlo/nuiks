# Catalog Service

`catalog-service` is the PostgreSQL-backed source of truth for StudyVault file metadata.

## Responsibilities

- persist canonical file metadata after uploads
- own folder structure, breadcrumbs, item listing, trash state, and restore metadata
- return authenticated Drive surfaces through `/api/v1/catalog/items`, `/api/v1/catalog/trash`, and `/api/v1/catalog/breadcrumbs/{folder_id}`
- expose internal metadata lookup and mutation routes for upload, restore, search reindex, and purge workflows

## Stored Metadata

The service tracks fields such as:

- `file_id`
- `owner_id`
- `filename`
- `mime_type`
- `size`
- `object_key`
- `tags`
- `created_at`

## Drive Semantics

- folders can be created at root or inside other folders
- files and folders can be moved between folders and back to root
- the service is the authoritative source for trash and restore behavior, including original parent tracking
- folder trash operations cascade to descendants and the purge workflow later removes expired trashed items
- restore operations can fall back when the original parent is gone and can return conflicts when the destination already contains the same name
- sibling name conflicts are validated here, making catalog-service the canonical authority for Drive structure and item-name uniqueness
