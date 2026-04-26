# Purge Worker

`purge-worker` is a background service responsible for permanently deleting expired items from the trash.

## Responsibilities

- query `catalog-service` for files and folders past their retention period (e.g., 30 days)
- issue internal hard-delete commands to `catalog-service` (PostgreSQL metadata), `file-service` (MinIO objects), and `search-service` (MongoDB index)
- ensure expired data is safely and completely removed from the system

## Behavior

- it is not an API service and exposes no HTTP ports
- runs securely in the background via Docker Compose (`PURGE_RUN_MODE=loop`)
- can also be executed as a one-off scheduled cron task (`PURGE_RUN_MODE=pass`)
- communicates exclusively over internal service-to-service endpoints (`/internal/...`) using `STUDYVAULT_INTERNAL_TOKEN`