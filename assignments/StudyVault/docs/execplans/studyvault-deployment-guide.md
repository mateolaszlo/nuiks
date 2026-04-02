# StudyVault Deployment Guide and Public Host Configuration

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document is maintained in accordance with `.AGENTS/PLANS.md` from the repository root.

## Purpose / Big Picture

After this change, a newcomer can deploy the full StudyVault stack without guessing how the services fit together. The repository now explains both the local or LAN path and the public Cloudflare-backed path, and the Docker Compose stack can follow a configured public hostname instead of assuming `localhost` everywhere. A user can prove the change works by setting `STUDYVAULT_PUBLIC_BASE_URL`, starting Docker Compose, and seeing Keycloak-backed login continue to work at either `http://localhost:8080`, a LAN IP, or a public Cloudflare hostname.

## Progress

- [x] (2026-04-02 10:55Z) Inspected the deployment-sensitive files, including the Docker Compose stack, nginx gateway, Keycloak realm import, and existing docs.
- [x] (2026-04-02 11:05Z) Reworked Compose so the frontend, backend issuer URLs, and Keycloak hostname follow `STUDYVAULT_PUBLIC_BASE_URL`, while admin and database ports default to host-local bind addresses.
- [x] (2026-04-02 11:12Z) Replaced the static Keycloak realm import with a template plus render step so redirect URIs and web origins follow the configured public base URL.
- [x] (2026-04-02 11:18Z) Updated the root README and StudyVault docs with a complete deployment runbook covering local, LAN, and Cloudflare-backed VM deployment.
- [x] (2026-04-02 11:28Z) Validated `docker compose ... config`, the smoke asset tests, and the templated Keycloak realm render for a non-localhost public base URL.

## Surprises & Discoveries

- Observation: the public deployment guide could not be truthful while the stack still hardcoded `http://localhost:8080` in Compose and the Keycloak realm import.
  Evidence: `assignments/StudyVault/infra/docker/compose/docker-compose.yml` and the original realm import under `assignments/StudyVault/infra/keycloak/` both encoded localhost URLs before this change.

- Observation: the Keycloak container image is already driven by shell commands in health checks, so a small shell render step was simpler and less risky than introducing another runtime dependency.
  Evidence: the existing health check already used `bash -c` against the Keycloak HTTP endpoint.

## Decision Log

- Decision: keep the root `README.md` concise and move the full operational checklist into `assignments/StudyVault/docs/deployment.md`.
  Rationale: the repository root should stay usable as an entrypoint, while the StudyVault deployment steps are long enough to deserve a focused runbook.
  Date/Author: 2026-04-02 / Codex

- Decision: parameterize the externally visible URL through `STUDYVAULT_PUBLIC_BASE_URL` instead of introducing multiple partially overlapping hostname variables.
  Rationale: one base URL is enough to drive frontend auth, backend issuer URLs, and Keycloak hostname behavior for this MVP.
  Date/Author: 2026-04-02 / Codex

- Decision: keep the gateway public by default and keep admin plus database ports bound to loopback by default.
  Rationale: this matches the desired public deployment posture while preserving easy local access on the same host.
  Date/Author: 2026-04-02 / Codex

- Decision: render the Keycloak realm import from a template during stack startup rather than storing separate realm files for local and public modes.
  Rationale: this avoids config drift and keeps one source of truth for the realm definition.
  Date/Author: 2026-04-02 / Codex

## Outcomes & Retrospective

The repository now documents full-stack deployment in a way that matches the stack configuration instead of describing an aspirational public deployment. Validation completed with `docker compose -f infra/docker/compose/docker-compose.yml config`, `PYTHONPATH=. .venv/bin/pytest -q tests/smoke/test_compose_assets.py`, and a rendered realm output showing `https://studyvault.example.com/*` as the Keycloak redirect URI. The largest remaining risk is validation depth: the docs and Compose changes can be checked locally, but a real public VM plus Cloudflare hostname still depends on the operator following the documented DNS and firewall steps correctly.

## Context and Orientation

StudyVault lives under `assignments/StudyVault`. The full runtime is defined in `assignments/StudyVault/infra/docker/compose/docker-compose.yml`. The public HTTP entrypoint is nginx, configured in `assignments/StudyVault/infra/nginx/nginx.conf`, and it proxies the React frontend, the FastAPI services, and proxied Keycloak realm paths. Keycloak bootstraps its realm from `assignments/StudyVault/infra/keycloak/`. A "realm import" is the JSON definition that creates the `studyvault` authentication realm, the frontend client, and the seeded users. The frontend uses Keycloak through `assignments/StudyVault/apps/frontend/src/auth/keycloak.ts`, where the external auth URL is supplied through the build environment.

The documentation entrypoints are `README.md` at the repository root, `assignments/StudyVault/README.md`, and markdown files under `assignments/StudyVault/docs/`. The new deployment guide must be detailed enough for a first-time operator to follow without reading source code.

## Plan of Work

First, rework the deployment configuration in `assignments/StudyVault/infra/docker/compose/docker-compose.yml` so the stack can derive its public-facing URL from one environment variable. The frontend `VITE_KEYCLOAK_URL`, backend `KEYCLOAK_ISSUER_URL`, and Keycloak `KC_HOSTNAME` must all follow that value. The same edit should move sensitive host port mappings to loopback by default so only the gateway is public unless the operator intentionally widens access.

Second, replace the static Keycloak realm file with a template plus a render step. The template should keep the existing realm roles and seeded users, but the redirect URI and web origin fields must be placeholders. A small shell script in `assignments/StudyVault/infra/scripts/` should render the final import file inside the container before Keycloak starts.

Third, update the docs. The repository root README should become a StudyVault entrypoint that links to the detailed deployment guide. The new `assignments/StudyVault/docs/deployment.md` must describe prerequisites, git commands, Python env setup, Docker Compose commands, local IP discovery, LAN deployment, Cloudflare DNS settings, public VM startup, validation URLs, troubleshooting exposure mode, and restart or rollback commands. Supporting docs should link to that runbook so there is one clear source of truth.

Finally, re-run the compose and smoke validations and record their outputs in this plan.

## Concrete Steps

Work from `assignments/StudyVault` unless a command says otherwise.

1. Validate the Compose file after the environment changes:

    docker compose -f infra/docker/compose/docker-compose.yml config

2. Run the smoke asset test from the StudyVault-local virtual environment:

    PYTHONPATH=. .venv/bin/pytest -q tests/smoke/test_compose_assets.py

3. Optionally render the Keycloak realm template locally to inspect the result:

    STUDYVAULT_PUBLIC_BASE_URL=https://studyvault.example.com sh infra/scripts/render_studyvault_realm.sh infra/keycloak/studyvault-realm.template.json /tmp/studyvault-realm.json

4. For a local stack check, start the stack:

    docker compose -f infra/docker/compose/docker-compose.yml up -d --build

5. Verify the runtime path:

    python3 tests/smoke/runtime_smoke.py

## Validation and Acceptance

Acceptance is reached when `docker compose ... config` succeeds, the smoke asset tests pass, the rendered Keycloak realm contains the correct redirect URL for a non-localhost base URL, and the docs explain enough steps for a first-time operator to bring the stack up on localhost, a LAN IP, or a Cloudflare-backed hostname. For a live stack, browsing to the configured public base URL must still reach the frontend login, and the Keycloak OpenID configuration must be reachable through `/realms/studyvault/.well-known/openid-configuration`.

## Idempotence and Recovery

The render step is safe to repeat because the `keycloak-realm-render` helper service overwrites the generated realm import file each time the stack starts. Updating `.env` and restarting Docker Compose is safe. If stale Keycloak or database state preserves old URLs, the recovery path is `docker compose down -v` followed by a clean `up -d --build`.

## Artifacts and Notes

Important file set produced by this work:

    README.md
    assignments/StudyVault/docs/deployment.md
    assignments/StudyVault/infra/docker/compose/docker-compose.yml
    assignments/StudyVault/infra/keycloak/studyvault-realm.template.json
    assignments/StudyVault/infra/scripts/render_studyvault_realm.sh

This plan was added during implementation because the repository instructions require an ExecPlan for significant configuration and documentation refactors.

## Interfaces and Dependencies

The deployment model depends on Docker Compose variable substitution, the nginx reverse proxy in `assignments/StudyVault/infra/nginx/nginx.conf`, and the Keycloak container import path `/opt/keycloak/data/import/`. The rendered realm template must still define the `studyvault-frontend` client and the `studyvault_admin` realm role. The compose stack must continue to expose the public app on host port `8080`, while keeping databases and admin tools on loopback by default.

Change note: this ExecPlan was created to document the deployment-guide and public-host refactor after discovering that the existing stack could not support a truthful public deployment guide while it still hardcoded `localhost`.
