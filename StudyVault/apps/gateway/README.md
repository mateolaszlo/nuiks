# Gateway

StudyVault uses nginx as the public gateway. The active gateway config is rendered from `infra/nginx/nginx.conf.template`.

## Routed Paths

- `/` -> frontend
- `/realms/`, `/resources/`, `/js/` -> Keycloak
- `/api/v1/files*` -> `file-service`
- `/api/v1/catalog/*` -> `catalog-service`
- `/api/v1/search*` -> `search-service`
- `/api/v1/activity/*` -> `activity-service`
- `/api/v1/admin/*` -> `activity-service`

The gateway fronts both the user-facing APIs and the admin API surface. Internal fan-out routes are not exposed through the public gateway. `file-service` calls the downstream services directly on the Compose network.

This directory remains reserved in case gateway-specific scripts or wrappers are needed later.
