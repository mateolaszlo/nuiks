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

## Behavior Notes

- public admin routes require an authenticated user with the `studyvault_admin` role
- permission failures use structured public responses such as `admin_access_required`
- user management actions are executed through Keycloak Admin APIs
- audit output combines Keycloak auth events with StudyVault application audit events
- health output summarizes recent uploads, downloads, searches, errors, and downstream service health
- error output is derived from structured logs indexed in Elasticsearch and is intended as the current operator-facing failure surface
