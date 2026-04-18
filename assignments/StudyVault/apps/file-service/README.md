# File Service

`file-service` handles the file binary workflow.

## Responsibilities

- accept authenticated uploads through `POST /api/v1/files`
- store file content in MinIO
- fan out file metadata to catalog, search, and activity services
- serve authenticated downloads from `GET /api/v1/files/{file_id}/download`

## Flow

For uploads, the service stores the object in MinIO first and then synchronously calls the downstream internal endpoints. Partial downstream failures are surfaced as errors and remain visible in logs rather than being silently rolled back.
