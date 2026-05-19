# StudyVault Microservices and Docker Compose

This document summarizes the currently used StudyVault services, their responsibilities, and how they are wired together in `infra/docker/compose/docker-compose.yml`.

## Overview

StudyVault runs as a small microservice system behind a single nginx gateway.

High-level flow:

1. The browser talks only to `gateway`.
2. `gateway` routes public traffic to the frontend, Keycloak, and the public `/api/v1/...` service endpoints.
3. The backend services communicate with each other over internal Compose networking through `/internal/...` routes.
4. Supporting infrastructure provides persistence, object storage, identity, and observability.

## Request Flow

### User-facing flow

- `frontend` serves the React/Vite application.
- `gateway` is the public entrypoint on port `8080`.
- `keycloak` handles login, registration, and account management.
- Public API requests are routed by `gateway` to:
  - `file-service`
  - `catalog-service`
  - `search-service`
  - `activity-service`

### Internal service flow

- `file-service` is the main binary workflow service.
- After an upload, `file-service` fans out metadata and activity to:
  - `catalog-service`
  - `search-service`
  - `activity-service`
- `purge-worker` performs scheduled hard-delete cleanup through internal service endpoints.
- `storage-usage-worker` periodically aggregates storage usage data from `catalog-service` into Elasticsearch.

Internal routes are not exposed through nginx. They are intended only for service-to-service calls inside the Compose network and are protected with `STUDYVAULT_INTERNAL_TOKEN`.

## Core Microservices

### `frontend`

Purpose:
- renders the StudyVault user and admin UI
- talks to the same-origin gateway

Key dependencies:
- `keycloak`
- `gateway`

Key environment:
- `VITE_KEYCLOAK_REALM`
- `VITE_KEYCLOAK_CLIENT_ID`

Exposure:
- internal container port only
- publicly reachable through `gateway`

### `gateway`

Purpose:
- nginx public reverse proxy
- single public entrypoint for browser traffic
- rate limiting and browser security headers

Key dependencies:
- `frontend`
- `file-service`
- `catalog-service`
- `search-service`
- `activity-service`
- `keycloak`

Key environment:
- `STUDYVAULT_AUTH_RATE`
- `STUDYVAULT_UPLOAD_RATE`
- `STUDYVAULT_SEARCH_RATE`
- `STUDYVAULT_ADMIN_RATE`

Exposure:
- public port `8080`

Routes handled:
- `/` -> frontend
- `/realms/`, `/resources/`, `/js/` -> Keycloak
- `/api/v1/files*` -> `file-service`
- `/api/v1/catalog/*` -> `catalog-service`
- `/api/v1/users/*` -> `catalog-service`
- `/api/v1/search*` -> `search-service`
- `/api/v1/activity/*` -> `activity-service`
- `/api/v1/admin/*` -> `activity-service`

### `catalog-service`

Purpose:
- PostgreSQL-backed source of truth for file and folder metadata
- owns drive structure, trash state, restore behavior, and usage totals

Key dependencies:
- `postgres`
- `keycloak`

Key environment:
- `CATALOG_DATABASE_URL`
- `KEYCLOAK_ISSUER_URL`
- `KEYCLOAK_JWKS_URL`
- `STUDYVAULT_INTERNAL_TOKEN`
- `USER_STORAGE_QUOTA_BYTES`

Exposure:
- internal service
- public API reachable only through `gateway`

Examples of owned behavior:
- drive item listing
- folder hierarchy
- trash and restore metadata
- per-user storage usage and quota values

### `file-service`

Purpose:
- accepts uploads
- stores file bytes in object storage
- serves downloads
- coordinates downstream metadata and activity fan-out

Key dependencies:
- `catalog-service`
- `search-service`
- `activity-service`
- external or local S3-compatible object storage
- `keycloak`

Key environment:
- `CATALOG_INTERNAL_URL`
- `SEARCH_INTERNAL_URL`
- `ACTIVITY_INTERNAL_URL`
- `FILE_S3_ENDPOINT`
- `FILE_S3_ACCESS_KEY`
- `FILE_S3_SECRET_KEY`
- `FILE_S3_BUCKET`
- `STUDYVAULT_INTERNAL_TOKEN`

Exposure:
- internal service
- public API reachable only through `gateway`

Notes:
- this is the service that calls the other backend services directly after upload
- upload quota enforcement depends on usage data exposed by `catalog-service`

### `search-service`

Purpose:
- stores denormalized search documents in MongoDB
- serves authenticated search results

Key dependencies:
- `mongodb`
- `keycloak`

Key environment:
- `SEARCH_MONGODB_URL`
- `KEYCLOAK_ISSUER_URL`
- `KEYCLOAK_JWKS_URL`
- `STUDYVAULT_INTERNAL_TOKEN`

Exposure:
- internal service
- public API reachable only through `gateway`

### `activity-service`

Purpose:
- stores per-user activity feed entries
- exposes the admin API surface
- integrates with Keycloak Admin APIs and observability data

Key dependencies:
- `mongodb`
- `keycloak`

Key environment:
- `ACTIVITY_MONGODB_URL`
- `KEYCLOAK_ADMIN_USERNAME`
- `KEYCLOAK_ADMIN_PASSWORD`
- `MAX_REGISTERED_USERS`
- `KEYCLOAK_ISSUER_URL`
- `KEYCLOAK_JWKS_URL`
- `STUDYVAULT_INTERNAL_TOKEN`

Exposure:
- internal service
- public activity and admin APIs reachable only through `gateway`

Notes:
- `/api/v1/admin/*` is currently served from this service
- admin operations include user enable/disable, role changes, audit, health, and password reset flows

### `keycloak`

Purpose:
- identity provider for login, registration, token issuance, and account management

Key dependencies:
- `postgres`
- `keycloak-realm-render`

Key environment:
- `KC_BOOTSTRAP_ADMIN_USERNAME`
- `KC_BOOTSTRAP_ADMIN_PASSWORD`
- `KC_DB_*`
- `KC_HOSTNAME`
- `STUDYVAULT_PUBLIC_BASE_URL`

Exposure:
- admin/debug port `8081` on the host
- browser traffic normally goes through `gateway`

## Background Services

### `purge-worker`

Purpose:
- permanently deletes expired trashed items

Key dependencies:
- `catalog-service`
- `file-service`
- `search-service`

Key environment:
- `CATALOG_INTERNAL_URL`
- `FILE_INTERNAL_URL`
- `SEARCH_INTERNAL_URL`
- `STUDYVAULT_INTERNAL_TOKEN`
- `PURGE_RUN_MODE`
- `PURGE_INTERVAL_SECONDS`

Exposure:
- no public HTTP surface

### `storage-usage-worker`

Purpose:
- periodically computes storage usage views for observability and reporting

Key dependencies:
- `catalog-service`
- `elasticsearch`

Key environment:
- `CATALOG_INTERNAL_URL`
- `ELASTICSEARCH_URL`
- `STUDYVAULT_INTERNAL_TOKEN`
- `STORAGE_USAGE_RUN_MODE`
- `STORAGE_USAGE_INTERVAL_SECONDS`
- `STORAGE_USAGE_INDEX_PREFIX`

Exposure:
- no public HTTP surface

### `keycloak-realm-render`

Purpose:
- renders the final Keycloak realm JSON from the checked-in template before Keycloak starts

Key environment:
- `STUDYVAULT_PUBLIC_BASE_URL`
- `MAX_REGISTERED_USERS`

Exposure:
- no public HTTP surface

### `kibana-setup`

Purpose:
- bootstraps Kibana saved objects and data views after Elasticsearch and Kibana are healthy

Exposure:
- no public HTTP surface

## Infrastructure and Observability Services

### Data services

#### `postgres`

Used for:
- StudyVault catalog metadata
- Keycloak relational storage

Persistent volume:
- `postgres-data`

#### `mongodb`

Used for:
- search index documents
- activity feed storage

Persistent volume:
- `mongodb-data`

#### `minio`

Used for:
- optional local S3-compatible object storage for file bytes

Profile:
- enabled only with `local-minio`

Persistent volume:
- `minio-data`

### Observability stack

#### `elasticsearch`

Used for:
- logs
- metrics
- storage usage views

Persistent volume:
- `elasticsearch-data`

#### `logstash`

Used for:
- ingesting GELF logs from containers and forwarding them to Elasticsearch

#### `kibana`

Used for:
- dashboards
- search and operations views

#### `metricbeat`

Used for:
- collecting Docker and host metrics

## Docker Compose Notes

### Why Compose is used here

`docker-compose.yml` defines the full local StudyVault environment:

- application services
- identity provider
- databases
- object storage
- observability stack
- startup ordering
- health checks
- persistent volumes

This allows the whole system to be started with one command and keeps the service topology consistent across development environments.

### Startup ordering

Compose uses `depends_on` with health conditions to reduce race conditions:

- backend services wait for their databases and Keycloak
- `gateway` waits for the frontend and public backend services
- `keycloak` waits for PostgreSQL and the rendered realm file
- workers wait for the services they call internally

### Public ports

The following host ports are commonly exposed:

- `8080` -> public gateway
- `8081` -> direct Keycloak access
- `5432` -> PostgreSQL
- `27017` -> MongoDB
- `9200` -> Elasticsearch
- `5601` -> Kibana
- `12201/udp` -> Logstash GELF input
- `9000` and `9001` -> MinIO API and console when `local-minio` is enabled

### Volumes

Defined persistent volumes:

- `postgres-data`
- `mongodb-data`
- `minio-data`
- `elasticsearch-data`
- `keycloak-import-data`

Their purpose is to keep service state across container restarts.

### Compose profiles

Current optional profile:

- `local-minio`: enables the local `minio` container

Without that profile, `file-service` expects an external S3-compatible endpoint from environment variables.

## Service Summary Table

| Service | Main role | Publicly exposed | Main storage/dependency |
| --- | --- | --- | --- |
| `frontend` | UI | Through gateway | Keycloak |
| `gateway` | Public reverse proxy | Yes | frontend + backend services |
| `catalog-service` | Metadata authority | Through gateway | PostgreSQL |
| `file-service` | Upload/download and fan-out | Through gateway | S3/MinIO + internal services |
| `search-service` | Search API | Through gateway | MongoDB |
| `activity-service` | Activity feed and admin API | Through gateway | MongoDB + Keycloak |
| `keycloak` | Identity provider | Through gateway and host `8081` | PostgreSQL |
| `purge-worker` | Expired trash cleanup | No | internal services |
| `storage-usage-worker` | Usage aggregation | No | catalog-service + Elasticsearch |
| `postgres` | Relational data | Host-local admin access | persistent volume |
| `mongodb` | Document data | Host-local admin access | persistent volume |
| `minio` | Local object storage | Host-local admin access | persistent volume |
| `elasticsearch` | Logs/metrics/storage views | Host-local admin access | persistent volume |
| `logstash` | Log ingestion | Host-local admin access | Elasticsearch |
| `kibana` | Dashboards | Host-local admin access | Elasticsearch |
| `metricbeat` | Metrics collection | No | Docker/host metrics |
| `keycloak-realm-render` | Realm template rendering | No | Keycloak import volume |
| `kibana-setup` | Kibana bootstrap | No | Kibana + Elasticsearch |
