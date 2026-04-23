# StudyVault Public API

This document covers the public HTTP API exposed through the StudyVault gateway. All documented routes are versioned under `/api/v1/...` and require a bearer token unless noted otherwise.

This file is the local API reference for the gateway-facing surface used by the frontend. Generated OpenAPI and Swagger endpoints are not part of the exposed application surface.

## Authentication and Errors

- Public routes expect `Authorization: Bearer <token>`.
- Most application-level failures use the shared structured error shape:

```json
{
  "detail": "Human-readable message",
  "code": "machine_readable_code",
  "category": "validation",
  "recoverable": true,
  "context": {},
  "field_errors": []
}
```

- Common categories are `validation`, `conflict`, `not_found`, `auth`, `permission`, and `unavailable`.
- Request validation failures raised directly by FastAPI can still return the default validation payload for malformed query parameters or bodies.

## Files

### `POST /api/v1/files`

Uploads a file into the authenticated user's drive.

- Content type: `multipart/form-data`
- Form fields:
  - `file`: required file payload
  - `tags`: optional repeated form field
  - `parent_folder_id`: optional destination folder id
- Response: [`FileRecord`](#response-models)
- Notable errors:
  - `401` when the bearer token is missing or invalid
  - `422` for invalid upload metadata or validation failures
  - `503` for storage or downstream sync failures such as `storage_unavailable` or `downstream_sync_failed`

### `GET /api/v1/files/{file_id}/download`

Downloads the raw file bytes for a file owned by the authenticated user.

- Response: streamed file content with the stored MIME type
- Notable errors:
  - `401` when the bearer token is missing or invalid
  - `404` when the file does not exist for the current user

### `PATCH /api/v1/files/{file_id}`

Renames a file.

- Request body:

```json
{
  "name": "new-name.pdf"
}
```

- Response: [`FileRecord`](#response-models)
- Notable errors:
  - `404` when the file does not exist
  - `409` when the destination folder already contains the same name
  - `422` for invalid names

### `POST /api/v1/files/{file_id}/move`

Moves a file into a folder or back to root.

- Request body:

```json
{
  "parent_folder_id": "folder-id-or-null"
}
```

- Response: [`FileRecord`](#response-models)
- Notable errors:
  - `404` when the file or destination folder does not exist
  - `409` when the target already has the same filename
  - `422` when the target is invalid, such as a trashed folder

### `DELETE /api/v1/files/{file_id}`

Moves a file to trash.

- Response: `204 No Content`
- Notable errors:
  - `404` when the file does not exist

### `POST /api/v1/files/{file_id}/restore`

Restores a trashed file.

- Request body:

```json
{
  "parent_folder_id": "optional-folder-id"
}
```

- Response: `FileRestoreResponse`
- Behavior:
  - restores to the original parent when possible
  - can restore to a requested destination when provided
  - can fall back to root when the original parent no longer exists

## Catalog

### `GET /api/v1/catalog/files`

Returns file records owned by the authenticated user.

- Response: array of [`FileRecord`](#response-models)

### `GET /api/v1/catalog/items`

Returns the Drive listing for a folder or for root.

- Query parameters:
  - `parent_id`: optional folder id
  - `include_trashed`: optional boolean, default `false`
- Response: `CatalogItemsResponse`

### `GET /api/v1/catalog/breadcrumbs/{folder_id}`

Returns the breadcrumb trail from root to a folder.

- Response: `CatalogBreadcrumbsResponse`
- Notable errors:
  - `404` when the folder does not exist

### `GET /api/v1/catalog/trash`

Returns trashed files and folders for the authenticated user.

- Response: `CatalogTrashResponse`

### `GET /api/v1/catalog/folders/{folder_id}`

Returns a folder record.

- Response: [`FolderRecord`](#response-models)
- Notable errors:
  - `404` when the folder does not exist

### `POST /api/v1/catalog/folders`

Creates a folder.

- Request body:

```json
{
  "name": "Projects",
  "parent_folder_id": null
}
```

- Response: [`FolderRecord`](#response-models)
- Status: `201 Created`
- Notable errors:
  - `404` when the parent folder does not exist
  - `409` when a sibling already uses the same name
  - `422` when the name is invalid

### `PATCH /api/v1/catalog/folders/{folder_id}`

Renames a folder.

- Request body:

```json
{
  "name": "Archived Projects"
}
```

- Response: [`FolderRecord`](#response-models)
- Notable errors:
  - `404` when the folder does not exist
  - `409` when a sibling already uses the same name
  - `422` when the name is invalid

### `DELETE /api/v1/catalog/folders/{folder_id}`

Moves a folder and its descendants to trash.

- Response: `204 No Content`
- Notable errors:
  - `404` when the folder does not exist

### `POST /api/v1/catalog/folders/{folder_id}/move`

Moves a folder to another parent or to root.

- Request body:

```json
{
  "parent_folder_id": "folder-id-or-null"
}
```

- Response: [`FolderRecord`](#response-models)
- Notable errors:
  - `404` when the folder or destination does not exist
  - `409` for move conflicts such as duplicate sibling names
  - `422` for invalid moves such as moving into a descendant

### `POST /api/v1/catalog/folders/{folder_id}/restore`

Restores a trashed folder.

- Request body:

```json
{
  "parent_folder_id": "optional-folder-id"
}
```

- Response: `CatalogRestoreResponse`
- Behavior:
  - attempts to restore to the original parent
  - can fall back to root when the original parent is gone
  - returns conflicts when the destination already contains the same name

## Search

### `GET /api/v1/search`

Searches the authenticated user's drive items.

- Query parameters:
  - `q`: search text, default empty string
  - `include_trashed`: optional boolean, default `false`
  - `kind`: `file`, `folder`, or `all`, default `all`
  - `parent_id`: optional folder filter
- Response: array of `DriveItem`
- Behavior:
  - current matching is case-insensitive across filename, MIME type, and tags
  - blank queries return an empty list
- Notable errors:
  - `401` when the bearer token is missing or invalid
  - `422` when `q` exceeds the configured limit, currently 100 characters

## Activity

### `GET /api/v1/activity/me`

Returns recent activity events for the authenticated user.

- Response: array of `ActivityRecord`

## Admin

Admin routes are served by `activity-service` and require a user with the `studyvault_admin` role.

### `GET /api/v1/admin/users`

Returns StudyVault users visible to the admin backend.

- Response: array of `AdminUserSummary`
- Notable errors:
  - `403` with `admin_access_required` when the caller is not an admin

### `POST /api/v1/admin/users/{user_id}/disable`

Disables a user account.

- Response: `AdminUserSummary`

### `POST /api/v1/admin/users/{user_id}/enable`

Re-enables a user account.

- Response: `AdminUserSummary`

### `POST /api/v1/admin/users/{user_id}/grant-admin`

Grants the `studyvault_admin` role.

- Response: `AdminUserSummary`

### `POST /api/v1/admin/users/{user_id}/revoke-admin`

Revokes the `studyvault_admin` role.

- Response: `AdminUserSummary`

### `POST /api/v1/admin/users/{user_id}/reset-password`

Resets a password and returns a temporary credential.

- Response: `AdminPasswordResetResult`

### `GET /api/v1/admin/audit`

Returns recent authentication and application audit events.

- Query parameters:
  - `limit`: optional integer, default `100`, max `200`
- Response: array of `AdminAuditEvent`

### `GET /api/v1/admin/health`

Returns a service and operations summary for admins.

- Response: `AdminHealthSummary`

### `GET /api/v1/admin/errors`

Returns recent operator-facing errors.

- Query parameters:
  - `limit`: optional integer, default `50`, max `200`
- Response: array of `AdminErrorRecord`

## Response Models

The most common public models are:

- `FileRecord`: file metadata including ids, name, MIME type, size, tags, timestamps, parent folder, and trash state
- `FolderRecord`: folder metadata including ids, name, parent folder, depth, timestamps, and trash state
- `DriveItem`: search and mixed listing item with `kind` set to `file` or `folder`
- `ActivityRecord`: user activity event with action, item context, message, and timestamp
- `CatalogItemsResponse`: mixed folder and file listing for a single parent
- `CatalogTrashResponse`: trashed files and folders
- `CatalogBreadcrumbsResponse`: breadcrumb entries from root to a folder
- `CatalogRestoreResponse`: restore result for folders
- `FileRestoreResponse`: restore result for files
- `AdminUserSummary`: admin-facing user account summary
- `AdminPasswordResetResult`: reset result including a temporary password
- `AdminAuditEvent`: admin-facing auth and application audit event
- `AdminHealthSummary`: service health and recent usage counters
- `AdminErrorRecord`: recent structured errors surfaced to administrators
