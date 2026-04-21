# Backend Common

`backend-common` is the shared Python package used across the FastAPI services.

## Shared Capabilities

- Keycloak JWT validation and auth dependency helpers
- request-aware structured logging
- environment-backed settings patterns
- shared data models for files, activity, authenticated users, and admin responses
- internal HTTP helper utilities for service-to-service calls
- versioned public FastAPI app assembly helpers
- structured public error helpers for stable user-facing contracts

## Structured Error Contract

Public services can raise `StudyVaultHTTPException` responses through the shared helpers in `studyvault_backend_common.errors`.

- public structured error payloads include `detail`, `code`, `category`, `recoverable`, optional `context`, and optional `field_errors`
- current categories are `conflict`, `validation`, `not_found`, `auth`, `permission`, `unavailable`, and `internal`
- the package also provides fallback category and code mapping for plain FastAPI `HTTPException` responses
- service-to-service callers preserve structured downstream details where available so callers can surface stable error codes instead of raw text only

## Current Auth Contract

- authenticated principals include `subject`, optional `email`, optional `username`, and `roles`
- the StudyVault admin role constant is `studyvault_admin`
- services can use the shared `is_admin` behavior on authenticated users and admin user summaries
- shared auth helpers emit stable public auth and permission codes such as `missing_bearer_token`, `invalid_token`, `unknown_signing_key`, and `admin_access_required`

## Versioning and HTTP Helpers

- `build_versioned_service_app(...)` mounts public routers under `/api/v1/...`
- internal `/internal/...` routes remain unversioned
- `/health` remains unversioned for service health checks
- shared HTTP client helpers normalize downstream failures into reusable exceptions for callers such as `file-service`
