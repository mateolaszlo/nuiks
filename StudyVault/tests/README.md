# StudyVault Test Guide

Run most commands from `StudyVault/` unless a command explicitly says otherwise.

## Prerequisites

Create the Python environment once:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Frontend browser tests use the frontend package dependencies:

```bash
cd apps/frontend
npm install
```

## Test Layout

The `tests/` directory contains the Python-based automated test suites:

- `tests/unit/`
  - shared library and helper behavior
  - examples: auth JWKS handling, logging, backend-common models, purge worker, response headers
- `tests/services/`
  - service-level API and repository tests with fakes/in-memory adapters
  - subdirectories:
    - `activity-service/`
    - `catalog-service/`
    - `file-service/`
    - `search-service/`
- `tests/integration/`
  - multi-service workflow checks without requiring the full browser stack
  - current example: upload flow
- `tests/smoke/`
  - local stack verification against Docker Compose
  - validates service health, auth stack readiness, observability assets, and runtime endpoints
- `tests/fixtures/`
  - reusable files for tests

Browser end-to-end tests are not under `tests/`; they live in:

- `apps/frontend/tests/e2e/studyvault.spec.ts`

## Fast Commands

Run all Python tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

Run a single Python file:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/unit/test_auth_jwks.py
```

Run a single test by name:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/services/file-service/test_file_api.py -k "upload_rejects_empty_content"
```

Run frontend typecheck/build:

```bash
npm run build --prefix apps/frontend
```

## Python Test Suites

### Unit tests

Run only unit tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/unit
```

These should not need Docker Compose.

### Service tests

Run all service tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/services
```

Run one service only:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/services/catalog-service
PYTHONPATH=. .venv/bin/pytest -q tests/services/file-service
PYTHONPATH=. .venv/bin/pytest -q tests/services/search-service
PYTHONPATH=. .venv/bin/pytest -q tests/services/activity-service
```

These tests usually rely on `tests/conftest.py`, which:

- injects test environment variables
- rewrites old public test paths like `/api/...` to `/api/v1/...`
- loads service apps directly with in-memory fakes

### Integration tests

Run integration tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/integration
```

Current coverage is lightweight and focused on cross-service behavior.

## Docker Compose Smoke Tests

These expect the full local stack to be running.

Start the stack:

```bash
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

If your user needs elevated permissions, use `sudo docker compose ...`.

Run smoke tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/smoke/test_compose_assets.py
python3 tests/smoke/runtime_smoke.py
```

What the smoke checks cover:

- Compose services become healthy
- Keycloak realm/bootstrap wiring
- PostgreSQL and MongoDB readiness
- gateway/frontend runtime availability
- Elasticsearch/Kibana/Logstash/Metricbeat observability setup
- structured logs reaching Elasticsearch

Stop the stack when finished:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down -v
```

## Frontend End-to-End Tests

Run these from `apps/frontend/`:

```bash
cd apps/frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 \
ELASTICSEARCH_URL=http://localhost:9200 \
npm run test:e2e
```

Equivalent direct Playwright command:

```bash
cd apps/frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 \
ELASTICSEARCH_URL=http://localhost:9200 \
npx playwright test tests/e2e/studyvault.spec.ts
```

Useful options:

```bash
npx playwright test tests/e2e/studyvault.spec.ts --grep "admin login"
npx playwright test tests/e2e/studyvault.spec.ts --headed
npx playwright test tests/e2e/studyvault.spec.ts --project=chromium
```

Required environment variables:

- `PLAYWRIGHT_BASE_URL`
  - normally `http://localhost:8080`
  - should point at the nginx gateway for the rebuilt Compose stack
- `ELASTICSEARCH_URL`
  - normally `http://localhost:9200`
  - used by tests that verify log ingestion

Recommended workflow for E2E:

1. rebuild the Compose stack after backend or frontend code changes
2. wait for healthy services
3. run the targeted Playwright tests first
4. run broader Playwright coverage only if needed
5. shut the stack down afterward if you started it for the test run

## Common Targeted Commands

Run only auth and logging unit tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/unit/test_auth_jwks.py tests/unit/test_logging.py
```

Run only file-service tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/services/file-service/test_file_api.py
```

Run only search-service tests:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/services/search-service/test_search_api.py
```

Run one Playwright scenario group:

```bash
cd apps/frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 \
ELASTICSEARCH_URL=http://localhost:9200 \
npx playwright test tests/e2e/studyvault.spec.ts --grep "upload|search|activity"
```

## Notes

- `PYTHONPATH=.` is required for the Python tests in this repository layout.
- Service tests do not normally require the Compose stack.
- Smoke tests and Playwright do require the Compose stack.
- If Playwright appears to be exercising stale code, rebuild the Compose stack before rerunning it.
- Some local environments require `sudo docker compose ...`; use the permission model that matches your machine.
