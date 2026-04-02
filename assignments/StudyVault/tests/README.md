# Automated Tests

StudyVault keeps most cross-service and environment validation in the top-level `tests/` directory.

## Test Layers

- `unit/` shared helpers such as auth and model behavior
- `services/` API-level service tests with fakes and dependency injection
- `integration/` multi-service workflow checks
- `smoke/` local-stack validation, including compose health, Keycloak/PostgreSQL checks, Kibana data view checks, and structured log ingestion
- `fixtures/` reusable files and payloads

## Common Commands

From `assignments/StudyVault`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/pytest -q
python3 tests/smoke/runtime_smoke.py
```

From the repo root:

```bash
cd assignments/StudyVault && PYTHONPATH=. .venv/bin/pytest -q
```

Frontend browser coverage lives in `apps/frontend/tests/e2e/` and is run with Playwright from the frontend package.
