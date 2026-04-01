# StudyVault

StudyVault is a runnable microservice MVP for managing study files. It includes a React frontend, an nginx gateway, four FastAPI services, Keycloak authentication, PostgreSQL, MongoDB, MinIO object storage, and an ELK-based logging stack.

## What It Does

- normal users can register, sign in, upload files, list their files, search metadata, review activity, and download files
- admins sign in to a separate admin console
- admins can list users, enable or disable accounts, grant or revoke the `studyvault_admin` role, reset passwords, inspect audit events, review service health, and see recent errors

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

From `assignments/StudyVault`:

```bash
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

To validate the stack:

```bash
PYTHONPATH=. .venv/bin/pytest -q
npm run build --prefix apps/frontend
python3 tests/smoke/runtime_smoke.py
docker compose -f infra/docker/compose/docker-compose.yml config
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
- `docs/` supporting notes such as Cloudflare deployment guidance and the living ExecPlan
- `studyvault_mvp_requirements.md` product requirements reference
