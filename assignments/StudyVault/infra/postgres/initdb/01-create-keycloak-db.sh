#!/bin/sh
set -eu

: "${KEYCLOAK_DB_USER:?KEYCLOAK_DB_USER must be set}"
: "${KEYCLOAK_DB_PASSWORD:?KEYCLOAK_DB_PASSWORD must be set}"

psql \
  -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v keycloak_db_user="$KEYCLOAK_DB_USER" \
  -v keycloak_db_password="$KEYCLOAK_DB_PASSWORD" <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN', :'keycloak_db_user')
WHERE NOT EXISTS (
   SELECT FROM pg_catalog.pg_roles
   WHERE rolname = :'keycloak_db_user'
)\gexec

SELECT format(
   'ALTER ROLE %I WITH LOGIN PASSWORD %L',
   :'keycloak_db_user',
   :'keycloak_db_password'
)\gexec

SELECT format('CREATE DATABASE %I OWNER %I', 'keycloak', :'keycloak_db_user')
WHERE NOT EXISTS (
   SELECT FROM pg_database
   WHERE datname = 'keycloak'
)\gexec

SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', 'keycloak', :'keycloak_db_user')\gexec
EOSQL
