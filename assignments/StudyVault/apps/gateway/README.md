# Gateway

StudyVault uses nginx as the public gateway. The active nginx configuration lives in `infra/nginx/nginx.conf`.

## Routed Paths

- `/` -> frontend
- `/realms/`, `/resources/`, `/js/` -> Keycloak
- `/api/files*` -> `file-service`
- `/api/catalog/*` -> `catalog-service`
- `/api/search*` -> `search-service`
- `/api/activity/*` -> `activity-service`
- `/api/admin/*` -> `activity-service`
- `/internal/catalog/*`, `/internal/search/*`, `/internal/activity/*` -> internal compose fan-out paths

This directory remains reserved in case gateway-specific scripts or wrappers are needed later.
