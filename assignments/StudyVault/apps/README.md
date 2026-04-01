# Applications

This directory contains the runnable StudyVault applications.

- `frontend/` Vite + React client with a normal user dashboard and a separate admin console
- `gateway/` nginx-facing app placeholder; the active gateway config lives in `infra/nginx/`
- `file-service/` FastAPI upload and download service backed by MinIO and synchronous fan-out to the other services
- `catalog-service/` FastAPI metadata service backed by PostgreSQL
- `search-service/` FastAPI metadata search service backed by MongoDB
- `activity-service/` FastAPI activity service plus the admin API surface for users, audit, health, and errors
