# ExecPlans
When writing complex features or significant refactors, use an ExecPlan (as described in .agent/PLANS.md) from design to implementation.

# Repository Guidelines

## Project Structure & Module Organization

StudyVault is a monorepo for a microservice-based MVP. Keep code and config grouped by responsibility:

- `apps/` runnable applications: `frontend`, `gateway`, `file-service`, `catalog-service`, `search-service`, `activity-service`
- `packages/` shared code such as backend auth, logging, config, and shared models
- `infra/` environment and deployment assets: Docker Compose, Nginx, Keycloak, observability, helper scripts
- `tests/` top-level automated test suites: `unit`, `services`, `integration`, `smoke`, `fixtures`
- `docs/` supporting architecture and setup notes
- `studyvault_mvp_requirements.md` product-level MVP scope

For backend services, keep FastAPI code under `app/api`, `app/core`, `app/models`, `app/schemas`, `app/services`, and `app/repositories`.

## Build, Test, and Development Commands

Use lightweight commands to inspect the repo and run tests:

```bash
git status
rg --files
find apps packages infra tests -maxdepth 3 -type d
pytest
```

`git status` checks pending work, `rg --files` lists tracked files, `find ...` verifies structure, and `pytest` runs the automated Python test layout defined in `pytest.ini`.

## Coding Style & Naming Conventions

Prefer lowercase directory and file names. Use descriptive names such as `file-service` and `backend-common`. Keep Markdown concise with short sections and fenced code blocks for commands and paths.

For Python services, follow the existing package layout and keep shared logic in `packages/backend-common` rather than duplicating helpers across services. Reserve `packages/frontend-common` for frontend code that is truly shared.

## Testing Guidelines

Automated tests are part of the project baseline:

- put service-local tests in `apps/*/tests/`
- put cross-service coverage in `tests/integration/`
- put compose or environment health checks in `tests/smoke/`
- keep reusable payloads and sample files in `tests/fixtures/`

Name Python tests `test_*.py` so they are discovered by `pytest`.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects such as `Add file-service skeleton` or `Update MVP requirements`. Keep each commit focused on one subsystem or documentation change.

In pull requests, summarize the affected area, list any new services, infra config, or test suites, and mention changes to public endpoints or environment assumptions when relevant.

## Assumption & Feedback Policy
- You are running in full-auto mode, but YOU MUST NOT hallucinate business logic, design choices, or missing architectural details.
- If a step in the specification is ambiguous, or you lack the necessary context to proceed safely, do the following:
  1. Stop coding.
  2. Output the exact phrase: `PAUSE_FOR_HUMAN:` followed by your specific question.
  3. Suspend your execution loop and wait for my response.
- Minor technical decisions (like how to structure a helper function) do not require permission. Make a reasonable choice and proceed.

## Testing and Execution Policy (NO REAL API KEYS)
Do NOT ask for real API keys. To verify that the project is working during development, use the following methods:

1. **Environment Variables**: Create a `.env.test` or `.env.example` file with dummy values (e.g., `STRIPE_KEY=sk_test_dummy123`).
2. **Mocking External APIs**: Whenever you write unit or integration tests, use mocking libraries (like `jest.mock`, `unittest.mock`, or `MSW` / Mock Service Worker). The tests should intercept network requests and return fake, successful JSON responses.
3. **Dependency Injection**: Design the code so that API clients can easily be swapped out with "fake" local versions during testing. 
4. **Static Analysis**: Rely heavily on structural checks to prove the code works. Run your compiler (e.g., `tsc --noEmit` for TypeScript), linters (`eslint`), and syntax checkers after every file creation to ensure there are no fatal errors.
