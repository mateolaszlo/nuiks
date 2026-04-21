# Activity Service

`activity-service` records per-user file activity and also exposes the gateway-facing admin APIs.

## Responsibilities

- store user activity events in MongoDB
- return the authenticated user activity feed from `GET /api/v1/activity/me`
- accept internal upload activity events from `POST /internal/activity/events`
- power admin operations under `/api/v1/admin/*`

## Admin Surface

This service currently hosts the StudyVault admin APIs:

- `GET /api/v1/admin/users`
- `POST /api/v1/admin/users/{user_id}/enable`
- `POST /api/v1/admin/users/{user_id}/disable`
- `POST /api/v1/admin/users/{user_id}/grant-admin`
- `POST /api/v1/admin/users/{user_id}/revoke-admin`
- `POST /api/v1/admin/users/{user_id}/reset-password`
- `GET /api/v1/admin/audit`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/errors`

Admin user management is executed through Keycloak Admin APIs. Audit and error summaries are built from the structured logs indexed in Elasticsearch.
