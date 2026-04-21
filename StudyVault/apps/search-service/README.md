# Search Service

`search-service` provides the user-facing metadata search API backed by MongoDB.

## Responsibilities

- store a denormalized search document for each uploaded file
- serve `GET /api/v1/search?q=...` for the authenticated user
- support internal indexing through `POST /internal/search/index`

## Search Behavior

The current implementation performs case-insensitive matching across filename, MIME type, and tags for the current authenticated user.

- public search is served from `GET /api/v1/search`
- search accepts `kind`, `include_trashed`, and `parent_id` filters
- trashed items are excluded by default and only appear when `include_trashed=true`
- query validation emits structured errors such as `search_query_too_long`
- internal indexing and deletion remain unversioned under `/internal/search/...`
