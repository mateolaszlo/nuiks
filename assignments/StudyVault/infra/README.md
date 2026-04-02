# Infrastructure

This directory contains the local runtime and deployment-support assets for StudyVault.

## Contents

- `docker/compose/` full local stack definition
- `nginx/` gateway routing config
- `keycloak/` realm bootstrap with self-registration, seeded users, and role definitions
- `postgres/` init scripts that create both the `studyvault` and `keycloak` databases on a fresh volume
- `observability/` Logstash and ELK pipeline config
- `scripts/` helper scripts such as Kibana bootstrap

## Local Stack Highlights

- Keycloak persists to PostgreSQL, not the embedded dev database
- the gateway is exposed on `http://localhost:8080`
- Kibana is exposed on `http://localhost:5601`
- logs are shipped with Docker GELF into Logstash and indexed in Elasticsearch
- the Keycloak client redirect URIs are rendered from `keycloak/studyvault-realm.template.json` using `STUDYVAULT_PUBLIC_BASE_URL`
- raw Keycloak, Kibana, Elasticsearch, MinIO, PostgreSQL, and MongoDB bind to loopback by default so only the gateway is public

If you change the Keycloak database bootstrap or similar infra assumptions, reset compose volumes before expecting a fresh local import.
