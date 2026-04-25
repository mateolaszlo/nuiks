# StudyVault

StudyVault is a runnable microservice application for personal file management. It includes a React frontend, an nginx gateway, four FastAPI services, Keycloak authentication, PostgreSQL, MongoDB, MinIO object storage, and an ELK-based logging stack.

For the full deployment runbook, including local IP access, Cloudflare-backed public hosting, firewall notes, and day-2 Docker commands, use [docs/deployment.md](docs/deployment.md).
For the public API reference, use [docs/api.md](docs/api.md).

Before any non-local deployment, set `KEYCLOAK_DB_PASSWORD`, `KC_BOOTSTRAP_ADMIN_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, and `STUDYVAULT_INTERNAL_TOKEN` in `.env` to non-default secrets. If `KEYCLOAK_ADMIN_PASSWORD` is unset, the activity-service admin client falls back to `KC_BOOTSTRAP_ADMIN_PASSWORD`.

## What It Does

- normal users can register, sign in, create folders, browse nested folders, upload and download files, rename and move items, send items to trash, restore items, search metadata, and review recent activity
- the Drive UI uses a grid-based workspace with single-select tiles, breadcrumb navigation, double-click folder open, a right-side details or activity panel, and a collapsible sidebar
- uploads support multi-file queueing, per-file progress, a processing state after bytes finish uploading, retry and dismiss for failures, automatic dismissal after success, and external drag-and-drop onto the current Drive surface, folders, and breadcrumbs
- search and Drive actions prefer local or inline recovery for create-folder, rename, move, upload, search, and auth/session failures instead of routing every problem through a single global banner
- admins sign in to a separate admin console
- admins can list users, enable or disable accounts, grant or revoke the `studyvault_admin` role, reset passwords, inspect audit events, review service health, and see recent errors

Public API routes exposed through the gateway are versioned under `/api/v1/...`.

## Local Stack

- app and auth gateway: `http://localhost:8080`
- raw Keycloak container: `http://localhost:8081`
- Kibana: `http://localhost:5601`
- Elasticsearch: `http://localhost:9200`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`
- PostgreSQL: `localhost:5432`
- MongoDB: `localhost:27017`

## Seeded Accounts

- user: `demo` / `demo123`
- app admin: `admin` / `admin123`

Self-registration is enabled through Keycloak. New users can create accounts from the frontend login screen.

## Run Locally

From `StudyVault`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

Use `.env.example` as the template for `.env` when starting the Docker Compose stack. Do not pass `.env.test` to `docker compose --env-file`; that file uses fake hosts such as `keycloak.test` and `catalog.test` for Python tests, not real container-to-container networking.

To validate the stack:

```bash
PYTHONPATH=. .venv/bin/pytest -q
npm run build --prefix apps/frontend
python3 tests/smoke/runtime_smoke.py
docker compose -f infra/docker/compose/docker-compose.yml config
```

Use [tests/README.md](tests/README.md) for the current test taxonomy, targeted `pytest` commands, smoke-test flow, and Playwright coverage details.

From the repo root, use the StudyVault-local virtualenv explicitly:

```bash
cd StudyVault && PYTHONPATH=. .venv/bin/pytest -q
```

Frontend browser E2E is available, but Playwright requires Node 18+:

```bash
cd apps/frontend
npm ci
npx playwright install --with-deps chromium
PLAYWRIGHT_BASE_URL=http://localhost:8080 ELASTICSEARCH_URL=http://localhost:9200 npm run test:e2e
```

## Repository Layout

- `apps/` runnable services and frontend
- `packages/` shared backend and future shared frontend code
- `infra/` compose, nginx, Keycloak, Postgres bootstrap, and observability config
- `tests/` unit, service, integration, fixtures, and smoke coverage
- `docs/` deployment and operational notes plus the docs index
- product requirements reference at the StudyVault root
