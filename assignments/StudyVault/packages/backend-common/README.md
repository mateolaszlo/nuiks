# Backend Common

`backend-common` is the shared Python package used across the FastAPI services.

## Shared Capabilities

- Keycloak JWT validation and auth dependency helpers
- request-aware structured logging
- environment-backed settings patterns
- shared data models for files, activity, authenticated users, and admin responses
- internal HTTP helper utilities for service-to-service calls

## Current Auth Contract

- authenticated principals include `subject`, optional `email`, optional `username`, and `roles`
- the StudyVault admin role constant is `studyvault_admin`
- services can use the shared `is_admin` behavior on authenticated users and admin user summaries
