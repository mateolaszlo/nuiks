# File Service

`file-service` handles the file binary workflow.

## Responsibilities

- accept authenticated uploads through `POST /api/v1/files`
- store file content in MinIO
- fan out file metadata to catalog, search, and activity services
- serve authenticated downloads from `GET /api/v1/files/{file_id}/download`
- handle public file rename, move, trash, and restore routes under `/api/v1/files/...`

## Flow

For uploads, the service stores the object in MinIO first and then synchronously calls the downstream internal endpoints. This is why the frontend queue distinguishes `uploading` from `processing`: bytes can finish uploading before downstream catalog, search, and activity sync has completed.

## Public Contract Notes

- public routes are versioned under `/api/v1/...`
- upload validation and operational failures use the shared structured error shape
- representative upload error codes include `upload_empty_file`, `upload_size_exceeded`, `storage_unavailable`, and `downstream_sync_failed`
- downstream sync failures can surface to the caller when catalog, search, or activity fan-out does not complete cleanly
