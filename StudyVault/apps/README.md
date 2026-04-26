# Applications

This directory contains the runnable StudyVault applications.

- `frontend/` Vite + React Drive-style client with a separate admin console
- `gateway/` nginx-facing app placeholder; the active gateway config lives in `infra/nginx/`
- `file-service/` FastAPI upload and file-lifecycle service backed by MinIO and synchronous fan-out to the other services
- `catalog-service/` FastAPI canonical metadata and Drive-structure service backed by PostgreSQL
- `search-service/` FastAPI metadata search service backed by MongoDB
- `activity-service/` FastAPI activity service plus the admin API surface for users, audit, health, and errors
- `purge-worker/` Dedicated background worker for purging files and metadata, loops hourly
