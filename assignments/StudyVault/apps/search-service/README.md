# Search Service

`search-service` provides the user-facing metadata search API backed by MongoDB.

## Responsibilities

- store a denormalized search document for each uploaded file
- serve `GET /api/search?q=...` for the authenticated user
- support internal indexing through `POST /internal/search/index`

## Search Behavior

The current MVP performs case-insensitive matching across filename, MIME type, and tags for the current authenticated user.
