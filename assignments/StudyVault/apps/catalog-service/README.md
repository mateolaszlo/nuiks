# Catalog Service

`catalog-service` is the PostgreSQL-backed source of truth for StudyVault file metadata.

## Responsibilities

- persist canonical file metadata after uploads
- return the authenticated user file list through `GET /api/catalog/files`
- expose internal metadata lookup and creation routes for the upload/download flow

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
