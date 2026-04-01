#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
DO
$$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE rolname = 'keycloak'
   ) THEN
      CREATE ROLE keycloak LOGIN PASSWORD 'keycloak';
   END IF;
END
$$;

SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (
   SELECT FROM pg_database
   WHERE datname = 'keycloak'
)\gexec

GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;
EOSQL
