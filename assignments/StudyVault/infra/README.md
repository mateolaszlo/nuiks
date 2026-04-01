# Infrastructure

Infrastructure and local-environment assets live here.

- `docker/compose/` Docker Compose definitions
- `nginx/` gateway config
- `keycloak/` realm and bootstrap config
- `postgres/` Postgres init scripts for local multi-database bootstrap
- `observability/` logging stack config
- `scripts/` helper scripts for local setup and CI

Keycloak now persists to PostgreSQL in local development. The shared `postgres` container creates both the `studyvault` and `keycloak` databases on a fresh volume bootstrap.
