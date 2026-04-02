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

Internal fan-out routes are not exposed through the public gateway. `file-service`
calls the downstream services directly on the Compose network.

This directory remains reserved in case gateway-specific scripts or wrappers are needed later.
