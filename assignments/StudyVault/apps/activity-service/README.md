# Activity Service

`activity-service` records per-user file activity and also exposes the gateway-facing admin APIs.

## Responsibilities

- store user activity events in MongoDB
- return the authenticated user activity feed from `GET /api/activity/me`
- accept internal upload activity events from `POST /internal/activity/events`
- power admin operations under `/api/admin/*`

## Admin Surface

This service currently hosts the StudyVault admin APIs:

- `GET /api/admin/users`
- `POST /api/admin/users/{user_id}/enable`
- `POST /api/admin/users/{user_id}/disable`
- `POST /api/admin/users/{user_id}/grant-admin`
- `POST /api/admin/users/{user_id}/revoke-admin`
- `POST /api/admin/users/{user_id}/reset-password`
- `GET /api/admin/audit`
- `GET /api/admin/health`
- `GET /api/admin/errors`

Admin user management is executed through Keycloak Admin APIs. Audit and error summaries are built from the structured logs indexed in Elasticsearch.
