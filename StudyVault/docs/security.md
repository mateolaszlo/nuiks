# StudyVault Security Notes

## Local `.env` workflow

Use `StudyVault/.env.example` only as the template for the local runtime file:

```bash
cp .env.example .env
```

`StudyVault/.env` is expected for local Docker Compose runs, but it is a local secret file. Do not commit it, copy it into screenshots, paste it into tickets, or share it outside the local machine where you run StudyVault.

`StudyVault/.env.test` is not a runtime secret file. It is a Python test fixture that intentionally uses fake hosts like `keycloak.test` and `catalog.test`, and it must not be passed to `docker compose --env-file`.

## Sensitive values

Before any shared, staged, or internet-exposed deployment, replace these defaults with unique secrets:

- `KEYCLOAK_DB_PASSWORD`
- `KC_BOOTSTRAP_ADMIN_PASSWORD`
- `KEYCLOAK_ADMIN_PASSWORD`
- `STUDYVAULT_INTERNAL_TOKEN`
- `FILE_S3_SECRET_KEY`

Treat any committed value for database URLs with embedded passwords, Keycloak admin credentials, MinIO secrets, private keys, or `STUDYVAULT_INTERNAL_TOKEN` as a secret leak and rotate it immediately.
