# StudyVault End-to-End Delivery

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document follows `.AGENTS/PLANS.md` from the repository root. Anyone continuing this work must keep this file current as implementation progresses.

## Purpose / Big Picture

After this work, a developer can start StudyVault locally, log in through Keycloak, upload a file, see it in a personal file list, search for it, review recent activity, and inspect JSON logs in Kibana. The implementation is intentionally focused, but it still demonstrates the required architecture: a frontend, an API gateway, four FastAPI services, PostgreSQL, MongoDB, MinIO, ELK, and CI automation.

The repository started as a scaffold with empty service directories. This plan turns that scaffold into a runnable project in clear milestones so another engineer can reproduce and extend it without guessing.

## Progress

- [x] 2026-03-31 09:35Z Read the StudyVault project specification, repository instructions, and execution-plan requirements.
- [x] 2026-03-31 09:52Z Confirmed `assignments/StudyVault` is a scaffold-only project on branch `testing`.
- [x] 2026-03-31 10:25Z Chose the initial implementation defaults: real Keycloak for auth and synchronous HTTP fan-out from `file-service` to the other services.
- [x] 2026-03-31 22:23Z Created shared backend helpers for auth, logging, HTTP clients, and shared schemas.
- [x] 2026-03-31 22:23Z Implemented the four FastAPI services with health checks, business endpoints, and test doubles.
- [x] 2026-03-31 23:02Z Added the React frontend, nginx routing, docker-compose stack, and local Keycloak realm bootstrap.
- [x] 2026-03-31 23:02Z Added automated tests, CI, smoke validation, and milestone checkpoints on `testing`.
- [x] 2026-04-01 00:40Z Moved local Keycloak persistence from the embedded dev database to the shared PostgreSQL container with a dedicated `keycloak` database and fresh realm reimport.
- [x] 2026-04-01 06:45Z Enabled Keycloak self-registration, seeded a StudyVault app admin, and added role-aware auth helpers.
- [x] 2026-04-01 06:45Z Added an admin-only console with user management, audit/event views, service health, and error summaries backed by admin APIs.
- [x] 2026-04-01 10:55Z Enriched logs with username/email identity fields and added Metricbeat-based host/container metrics plus a Kibana metrics data view.

## Surprises & Discoveries

- Observation: The sandbox permits some read-only shell commands but rejects others with a loopback-network namespace error.
  Evidence: Commands such as `git branch --list testing` succeeded while multiple `sed` and `git status` calls initially failed with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.

- Observation: Every service directory already matches the expected FastAPI layout, but the code itself was empty.
  Evidence: `find assignments/StudyVault/apps assignments/StudyVault/packages assignments/StudyVault/infra assignments/StudyVault/tests -type f | grep -v '/.venv/' | sort` returned only README files, `__init__.py`, and `.gitkeep`.

- Observation: Import-time FastAPI app construction made tests try to contact MongoDB and MinIO before fakes could be injected.
  Evidence: The implementation required a `STUDYVAULT_SKIP_APP_BOOTSTRAP` environment flag so pytest could import service modules without eager external initialization.

- Observation: The available Node runtime is `v16.17.1`, which is too old for current Vite 5 packages.
  Evidence: `npm install` warned that `vite@5.4.21` and `rollup@4.60.1` require Node 18+, so the frontend toolchain was pinned to Node-16-compatible versions before the build.

- Observation: The first nginx draft only routed the public `/api/*` paths, which would have broken the upload fan-out inside Docker Compose.
  Evidence: `file-service` publishes to `/internal/catalog/*`, `/internal/search/*`, and `/internal/activity/*`, so explicit internal gateway routes had to be added before compose validation.

- Observation: Keycloak was initially using its embedded dev database, so auth state depended on container-local storage rather than the repo-defined infra stack.
  Evidence: The `keycloak` compose service only ran `start-dev --import-realm` and did not define any `KC_DB*` environment or Postgres dependency before this migration.

- Observation: nginx served the frontend HTML for `/api/admin/*` even after the admin routes were added.
  Evidence: `curl -i http://localhost:8080/api/admin/users` returned the Vite `index.html` until the proxy configuration was changed to pass `$request_uri` explicitly and give `/api/admin/` a dedicated `^~` location.

## Decision Log

- Decision: Implement real Keycloak wiring rather than a frontend mock-auth shortcut.
  Rationale: The project requirements call out Keycloak as a mandatory component, and the local compose stack can demonstrate it without external credentials.
  Date/Author: 2026-03-31 / Codex

- Decision: Use synchronous HTTP fan-out from `file-service` to `catalog-service`, `search-service`, and `activity-service`.
  Rationale: The requirements do not define a broker, and direct service calls are the smallest design that still preserves microservice boundaries for the project.
  Date/Author: 2026-03-31 / Codex

- Decision: Keep test suites primarily on in-memory fakes and dependency injection instead of requiring live PostgreSQL, MongoDB, and MinIO during unit and service tests.
  Rationale: The repository policy forbids real credentials and asks for mocking and structural validation where possible.
  Date/Author: 2026-03-31 / Codex

- Decision: Reuse the shared PostgreSQL container for Keycloak, but isolate it in its own `keycloak` database and user.
  Rationale: This keeps local infrastructure simple while avoiding auth data mixing with the application metadata schema.
  Date/Author: 2026-04-01 / Codex

- Decision: Route admins to a separate admin console instead of showing the normal user dashboard with extra controls.
  Rationale: Admin workflows are operational, not personal-content-centric. A dedicated console makes audit, user management, health, and error views explicit and reduces accidental coupling with the normal user experience.
  Date/Author: 2026-04-01 / Codex

- Decision: Implement the admin API surface inside `activity-service` first, using Keycloak Admin APIs plus Elasticsearch-backed summaries.
  Rationale: The activity service already owns user-scoped events, and extending it keeps the first admin cut small while still avoiding direct browser access to Keycloak Admin APIs or Elasticsearch.
  Date/Author: 2026-04-01 / Codex

## Outcomes & Retrospective

No milestone has completed yet. The initial outcome is that the repository now has a decision-complete direction and a living document that must be updated as code lands.

The project now includes the backend services, a React frontend, local container orchestration, a PostgreSQL-backed Keycloak realm bootstrap, smoke validation, and a GitHub Actions workflow. Existing local environments must reset Compose volumes before the new Keycloak Postgres init script takes effect.

The current implementation also includes self-registration, a seeded `studyvault_admin` user, and a dedicated admin console. Admins can list users, enable or disable accounts, grant or revoke the StudyVault admin role, trigger temporary-password resets, inspect audit events, review service health, and see recent application errors.

Observability now includes structured request and business-event logs with user-friendly identity fields where available, plus Metricbeat-fed host and container resource metrics exposed through a separate `metricbeat-*` Kibana data view.

## Context and Orientation

The project root for this feature is `assignments/StudyVault`. Backend applications live in `apps/file-service`, `apps/catalog-service`, `apps/search-service`, and `apps/activity-service`. Each service keeps FastAPI code under `app/api`, `app/core`, `app/models`, `app/schemas`, `app/services`, and `app/repositories`.

Shared Python code belongs in `packages/backend-common`. Frontend code belongs in `apps/frontend/src`. Infrastructure assets belong in `infra/docker/compose`, `infra/nginx`, `infra/keycloak`, and `infra/observability`. Top-level tests belong in `tests/unit`, `tests/services`, `tests/integration`, and `tests/smoke`.

The repository uses FastAPI, SQLAlchemy, boto3, pymongo, structlog, and pytest from `requirements.txt`. No service-specific implementation existed at the start of this plan.

## Plan of Work

First, create a small shared Python package under `packages/backend-common/studyvault_backend_common`. It must provide:

1. Pydantic models for common file metadata, activity events, search documents, and authenticated users.
2. Structured logging setup and request-id middleware helpers.
3. JWT validation helpers that support Keycloak in production and explicit auth bypass in tests.
4. HTTP client helpers with retry support for internal service-to-service JSON requests.

Next, implement each backend service. `catalog-service` stores metadata in PostgreSQL and exposes public file-list endpoints plus a private metadata-create endpoint for `file-service`. `search-service` stores a denormalized searchable copy in MongoDB and supports internal indexing plus public search. `activity-service` stores activity records in MongoDB and supports internal event creation plus public readback. `file-service` receives uploads, stores the file in MinIO, then calls the three downstream services synchronously before returning the final file metadata. It also serves downloads by asking `catalog-service` for the canonical object metadata and then streaming from MinIO.

Then, create the frontend with a single authenticated dashboard page. It must use Keycloak for login, call nginx-routed API endpoints, show upload/search/activity sections, and offer download links. Add nginx config to proxy frontend assets, the four API prefixes, and the Keycloak realm paths.

Extend that foundation with role-aware frontend routing and a dedicated admin console. The admin console must call app-owned admin APIs, not raw Elasticsearch or Keycloak Admin APIs from the browser, and it must expose user management, audit visibility, health summaries, and recent error information.

Finally, create the docker-compose stack, local realm import, logstash and kibana configuration, smoke and integration tests, and a GitHub Actions workflow. Keep commits focused on milestones and update this plan after each milestone.

## Concrete Steps

Work from `assignments/StudyVault`.

1. Create the local Python environment and install dependencies:
      python3 -m venv .venv
      .venv/bin/pip install -r requirements.txt
2. Build the shared backend package and backend service code.
3. Run:
      PYTHONPATH=. .venv/bin/pytest -q
4. Build the frontend package and static checks.
5. Run:
      npm install
      npm run build
6. Validate compose definitions:
      docker compose -f infra/docker/compose/docker-compose.yml config
7. Start the full stack and verify the demo flow:
      docker compose -f infra/docker/compose/docker-compose.yml up --build

Expected acceptance includes `/health` responses from all services, a working Keycloak login, a successful upload, file listing, search hits, activity records, and visible JSON logs in Kibana.

Admin acceptance includes a working admin login, a separate admin landing experience, a visible user list, working enable/disable and role-grant actions, and an admin health summary backed by live services.

## Validation and Acceptance

The implementation is complete when these behaviors are true:

- Running `PYTHONPATH=. .venv/bin/pytest -q` from `assignments/StudyVault` passes.
- Building the frontend succeeds without TypeScript errors.
- `docker compose ... config` validates successfully.
- Starting the compose stack exposes the frontend on `http://localhost:8080/`.
- Logging in with the seeded demo user reaches the dashboard.
- Logging in with the seeded admin user reaches the admin console instead of the normal user dashboard.
- Uploading a file produces a file list entry, a search hit, and an activity record for the same authenticated user.
- Downloading the file returns the original content.
- Kibana can show upload and search logs for the session.
- Admin APIs can list users, return service health, and expose audit/error summaries for the session.

## Idempotence and Recovery

All file-creation and service-start steps are additive. Re-running tests is safe. Re-running startup should recreate missing tables, missing Mongo indexes, and the MinIO bucket if needed. If a compose startup leaves stale state, remove containers and volumes with Docker Compose before retrying. If a downstream service call fails after MinIO upload, the system currently prefers a visible error and log evidence over compensating deletes; this is an implementation tradeoff and should be documented rather than hidden.

## Artifacts and Notes

The most important commands to preserve during implementation are:

    PYTHONPATH=. .venv/bin/pytest -q
    npm run build
    docker compose -f infra/docker/compose/docker-compose.yml config
    docker compose -f infra/docker/compose/docker-compose.yml up --build

Keep short transcripts of successful health checks and at least one upload request in this section once those milestones complete.

    $ PYTHONPATH=. .venv/bin/pytest -q
    .........                                                                [100%]
    9 passed in 1.11s

    $ npm run build
    vite v4.5.5 building for production...
    ✓ built in 1.68s

    $ docker compose -f infra/docker/compose/docker-compose.yml config
    services:
      frontend:
      gateway:
      keycloak:
      file-service:
      catalog-service:
      search-service:
      activity-service:
      postgres:
      mongodb:
      minio:
      elasticsearch:
      logstash:
      kibana:

## Interfaces and Dependencies

The shared package must expose these types:

    studyvault_backend_common.models.AuthenticatedUser
    studyvault_backend_common.models.FileRecord
    studyvault_backend_common.models.ActivityRecord
    studyvault_backend_common.models.UploadActivityEvent

The backend services must expose these public routes:

    POST /api/files
    GET /api/files/{file_id}/download
    GET /api/catalog/files
    GET /api/search?q=...
    GET /api/activity/me

The backend services may expose these internal routes for compose-only fan-out:

    POST /internal/catalog/files
    GET /internal/catalog/files/{file_id}
    POST /internal/search/index
    POST /internal/activity/events

The gateway-facing admin surface now also includes:

    GET /api/admin/users
    POST /api/admin/users/{user_id}/enable
    POST /api/admin/users/{user_id}/disable
    POST /api/admin/users/{user_id}/grant-admin
    POST /api/admin/users/{user_id}/revoke-admin
    POST /api/admin/users/{user_id}/reset-password
    GET /api/admin/audit
    GET /api/admin/health
    GET /api/admin/errors

Update note: revised on 2026-03-31 after the frontend, compose, smoke-test, and CI milestones landed so the plan matches the repository and recorded validation results.
