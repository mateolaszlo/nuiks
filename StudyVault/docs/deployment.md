# StudyVault Deployment Guide

This guide covers the full StudyVault stack in two modes:

- local or LAN deployment from a workstation or home server
- public deployment on a single Linux VM behind Cloudflare

The same Docker Compose file drives both modes. The difference is the public base URL you choose and which host ports you bind publicly.

## What This Stack Exposes

By default, the gateway is reachable on port `8080` and everything else stays host-local:

- public app entrypoint: `http://<host>:8080`
- raw Keycloak container: `http://127.0.0.1:8081`
- Kibana: `http://127.0.0.1:5601`
- Elasticsearch: `http://127.0.0.1:9200`
- PostgreSQL: `127.0.0.1:5432`
- MongoDB: `127.0.0.1:27017`

The file-service does not require the bundled MinIO container anymore. Its storage target comes from `FILE_S3_ENDPOINT`, `FILE_S3_ACCESS_KEY`, `FILE_S3_SECRET_KEY`, `FILE_S3_BUCKET`, and `FILE_S3_REGION`. The recommended deployment path is a dedicated external MinIO or another S3-compatible service reachable from the VM. The bundled MinIO container is still available through the optional Compose profile `local-minio`.

The environment variables that control this behavior are in `StudyVault/.env.example`.

## Shared Prerequisites

Assume an Ubuntu or Debian-like Linux host with Docker Engine, the Docker Compose plugin, Git, and Python 3.12 or newer.

Install the required tools:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin python3 python3-venv
sudo usermod -aG docker "$USER"
newgrp docker
```

Clone the repository and move into the StudyVault project:

```bash
git clone https://github.com/mateolaszlo/nuiks.git
cd nuiks/StudyVault
```

Create the local Python environment used for smoke tests and validation:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Create the deployment environment file:

```bash
cp .env.example .env
```

## Environment Variables You Must Understand

Edit `.env` before starting the stack.

- `STUDYVAULT_PUBLIC_BASE_URL` is the externally visible app URL. For local use it stays `http://localhost:8080`. For LAN use it becomes something like `http://192.168.1.50:8080`. For Cloudflare use it becomes something like `https://studyvault.example.com`.
- `STUDYVAULT_GATEWAY_BIND_ADDRESS` controls whether the main gateway listens only on localhost or on all interfaces. Keep `0.0.0.0` when other devices must reach the app.
- `STUDYVAULT_AUTH_RATE` and `STUDYVAULT_AUTH_BURST` control nginx throttling for Keycloak login traffic. The `.env.example` defaults are intentionally relaxed for local development and Playwright runs; tighten them for any shared or internet-exposed deployment.
- `STUDYVAULT_UPLOAD_RATE` and `STUDYVAULT_UPLOAD_BURST` control nginx throttling for file-upload requests.
- `STUDYVAULT_SEARCH_RATE` and `STUDYVAULT_SEARCH_BURST` control nginx throttling for search traffic.
- `STUDYVAULT_ADMIN_RATE` and `STUDYVAULT_ADMIN_BURST` control nginx throttling for admin-panel API calls. The defaults are intentionally higher than the other interactive routes so enable/disable and password-reset workflows do not trip `429` under normal use.
- `STUDYVAULT_ADMIN_BIND_ADDRESS` controls raw Keycloak, Kibana, Elasticsearch, MinIO, and Logstash host exposure. Keep `127.0.0.1` unless you are intentionally opening troubleshooting access.
- `STUDYVAULT_DB_BIND_ADDRESS` controls PostgreSQL and MongoDB host exposure. Keep `127.0.0.1`.
- `FILE_S3_ENDPOINT`, `FILE_S3_ACCESS_KEY`, `FILE_S3_SECRET_KEY`, `FILE_S3_BUCKET`, and `FILE_S3_REGION` configure object storage for `file-service`. For dedicated MinIO, use the S3 API port, typically `9000`, not the web console port.

For dedicated external MinIO or other S3-compatible storage, the configured bucket should already exist and be accessible to the supplied credentials before StudyVault starts. When the optional bundled `local-minio` profile is enabled, `file-service` will create the configured bucket automatically if it is missing and the credentials permit bucket creation.

StudyVault renders the Keycloak realm import from `infra/keycloak/studyvault-realm.template.json` through the `keycloak-realm-render` helper service before Keycloak starts. That means the login redirect URIs follow `STUDYVAULT_PUBLIC_BASE_URL` automatically. You do not need to hand-edit the Keycloak JSON for each deployment.

Keycloak now uses a dedicated PostgreSQL role created from `KEYCLOAK_DB_USER` and `KEYCLOAK_DB_PASSWORD`. Leave the username at `keycloak` unless you have a reason to change it, but set a non-default database password before any VM or shared-host deployment. The same values are consumed by both the Postgres init script and the Keycloak container, so they must stay in sync.

The activity-service admin APIs authenticate to Keycloak with `KEYCLOAK_ADMIN_USERNAME` and `KEYCLOAK_ADMIN_PASSWORD`. If those are unset, StudyVault falls back to `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD`, so the example environment keeps them aligned by default.

## Local Laptop or Single-Host Deployment

Leave `.env` close to the defaults:

```dotenv
STUDYVAULT_PUBLIC_BASE_URL=http://localhost:8080
STUDYVAULT_GATEWAY_BIND_ADDRESS=0.0.0.0
STUDYVAULT_ADMIN_BIND_ADDRESS=127.0.0.1
STUDYVAULT_DB_BIND_ADDRESS=127.0.0.1
STUDYVAULT_AUTH_RATE=120r/m
STUDYVAULT_AUTH_BURST=30
KEYCLOAK_DB_USER=keycloak
KEYCLOAK_DB_PASSWORD=studyvault-keycloak-db-password-change-me
STUDYVAULT_ADMIN_RATE=120r/m
STUDYVAULT_ADMIN_BURST=30
FILE_S3_ENDPOINT=http://10.0.0.10:9000
FILE_S3_ACCESS_KEY=replace-with-minio-access-key
FILE_S3_SECRET_KEY=replace-with-minio-secret-key
FILE_S3_BUCKET=studyvault-files
FILE_S3_REGION=us-east-1
```

Start the full stack:

```bash
sudo docker compose --env-file StudyVault/.env -f StudyVault/infra/docker/compose/docker-compose.yml up -d --build
```

If you want the bundled local MinIO container instead of a dedicated external MinIO service, change the storage variables in `.env` to:

```dotenv
FILE_S3_ENDPOINT=http://minio:9000
FILE_S3_ACCESS_KEY=minioadmin
FILE_S3_SECRET_KEY=minioadmin
FILE_S3_BUCKET=studyvault-files
FILE_S3_REGION=us-east-1
```

and start Compose with the profile from the repo root (`nuiks/`):

```bash
sudo docker compose --profile local-minio --env-file StudyVault/.env.example -f StudyVault/infra/docker/compose/docker-compose.yml up -d --build
```

Check that Docker Compose accepted the configuration:

```bash
docker compose -f infra/docker/compose/docker-compose.yml config
docker compose -f infra/docker/compose/docker-compose.yml ps
```

Validate the app and observability stack:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/smoke/test_compose_assets.py
python3 tests/smoke/runtime_smoke.py
```

Use [../tests/README.md](../tests/README.md) for the broader test matrix, targeted `pytest` commands, and Playwright E2E workflow.

For the currently validated local E2E path, start the stack from the repo root (`nuiks/`) with:

```bash
sudo docker compose --profile local-minio --env-file StudyVault/.env.example -f StudyVault/infra/docker/compose/docker-compose.yml up -d --build
```

Then run Playwright from `nuiks/StudyVault/apps/frontend` with:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:8080 ELASTICSEARCH_URL=http://localhost:9200 npm run test:e2e
```

Open these URLs on the same machine:

- app and Keycloak-proxied login: `http://localhost:8080`
- raw Keycloak admin endpoint: `http://127.0.0.1:8081`
- Kibana: `http://127.0.0.1:5601`
- Elasticsearch: `http://127.0.0.1:9200`

When the optional `local-minio` profile is enabled:

- MinIO API: `http://127.0.0.1:9000`
- MinIO console: `http://127.0.0.1:9001`

Seeded accounts:

- normal user: `demo` / `demo123`
- admin user: `admin` / `admin123`

## LAN Deployment With a Local IP

Find the host IP address that other devices on the network can reach:

```bash
hostname -I
ip addr show
```

Pick the correct private address, for example `192.168.1.50`, and set `.env` like this:

```dotenv
STUDYVAULT_PUBLIC_BASE_URL=http://192.168.1.50:8080
STUDYVAULT_GATEWAY_BIND_ADDRESS=0.0.0.0
STUDYVAULT_ADMIN_BIND_ADDRESS=127.0.0.1
STUDYVAULT_DB_BIND_ADDRESS=127.0.0.1
```

Restart the stack after changing `.env`:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

Other devices on the same network should browse to `http://192.168.1.50:8080`. Keep Kibana, MinIO, Elasticsearch, PostgreSQL, and MongoDB on `127.0.0.1` unless you are actively debugging.
If you are using dedicated external MinIO, the MinIO host itself stays outside this Compose stack; only `file-service` needs network reachability to its S3 API port.

## Public Deployment on a Linux VM Behind Cloudflare

Assume one public Linux VM and one DNS name such as `studyvault.example.com`.

### 1. Prepare the VM

Run the shared prerequisites on the VM, then clone the repo:

```bash
git clone https://github.com/mateolaszlo/nuiks.git
cd nuiks/StudyVault
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Set `.env` for the public hostname:

```dotenv
STUDYVAULT_PUBLIC_BASE_URL=https://studyvault.example.com
STUDYVAULT_GATEWAY_BIND_ADDRESS=0.0.0.0
STUDYVAULT_ADMIN_BIND_ADDRESS=127.0.0.1
STUDYVAULT_DB_BIND_ADDRESS=127.0.0.1
KEYCLOAK_DB_USER=keycloak
KEYCLOAK_DB_PASSWORD=replace-with-a-strong-secret
STUDYVAULT_ADMIN_RATE=120r/m
STUDYVAULT_ADMIN_BURST=30
```

Change `KEYCLOAK_DB_PASSWORD`, `KC_BOOTSTRAP_ADMIN_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, and `STUDYVAULT_INTERNAL_TOKEN` before exposing the stack outside your own machine.

### 2. Open Only the Ports You Need

The minimum public port is `8080` on the VM because nginx inside the Compose stack listens there on the host. Keep every other mapped service on `127.0.0.1`. 

To securely restrict access so that only Cloudflare can reach the application, use UFW to whitelist Cloudflare's IP ranges alongside your SSH port:

```bash
# Allow SSH access
sudo ufw allow 22/tcp

# Allow Cloudflare IPv4 ranges to port 8080
for ip in $(curl -s https://www.cloudflare.com/ips-v4); do sudo ufw allow from $ip to any port 8080 proto tcp; done

# Allow Cloudflare IPv6 ranges to port 8080
for ip in $(curl -s https://www.cloudflare.com/ips-v6); do sudo ufw allow from $ip to any port 8080 proto tcp; done

# Then deny all other access to port 8080
sudo ufw deny 8080

sudo ufw enable
sudo ufw status
```

### 3. Configure Cloudflare

Create or update the DNS record:

- type: `A`
- name: the host you want, for example `studyvault`
- content: the VM public IPv4 address
- proxy status: proxied

Use these Cloudflare settings:

- SSL/TLS mode: `Flexible`
- Always Use HTTPS: enabled
- Automatic HTTPS Rewrites: enabled

StudyVault does not terminate TLS on the VM itself. Cloudflare provides the browser-facing HTTPS layer and forwards traffic to the origin on port `8080`. The nginx config must preserve the browser-facing HTTPS scheme from Cloudflare headers rather than trusting the origin hop alone, otherwise Keycloak can reject login with `ssl_required`.

The nginx gateway also restores the real client IP from `CF-Connecting-IP`, but only when the request source matches the checked-in Cloudflare proxy CIDRs in `infra/nginx/cloudflare-realip.conf`. This keeps nginx rate limits keyed to the browser client instead of the Cloudflare edge IP while still rejecting spoofed client-IP headers from untrusted direct origin traffic.

If uploads or other same-origin API calls show a browser warning such as `Content-Security-Policy-Report-Only ... connect-src 'none'`, verify the header at the public hostname before changing the app stack. The checked-in nginx template in `infra/nginx/nginx.conf.template` renders an enforcing CSP with `connect-src 'self'`, so a stricter report-only header usually means Cloudflare or another edge proxy is injecting it. Confirm the public response headers for both `/` and `/api/v1/files`, and make sure any edge-managed CSP or CSP report-only policy still allows same-origin `connect-src` requests.

### 4. Start the Stack

```bash
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
docker compose -f infra/docker/compose/docker-compose.yml ps
```

### 5. Validate the Public Deployment

On the VM:

```bash
curl -I http://127.0.0.1:8080
curl -I http://127.0.0.1:8080/realms/studyvault/.well-known/openid-configuration
python3 tests/smoke/runtime_smoke.py
```

From a browser:

- `https://studyvault.example.com`
- log in as `demo` or `admin`
- upload a file
- confirm the file appears in the Drive grid, search results, and activity feed

If you observe unexpected shared `429` responses behind Cloudflare, inspect the current Cloudflare proxy IP list and refresh `infra/nginx/cloudflare-realip.conf` if Cloudflare has added or changed ranges since the repo version you deployed.

Do not use `http://<public-ip>:8080` or `https://<public-ip>:8080` as the real auth-path test for a public deployment. The intended path is the Cloudflare-backed `https://` hostname without an explicit port.

If you need local-only observability on the VM, tunnel or SSH in first:

```bash
ssh user@studyvault-vm
curl http://127.0.0.1:5601/api/status
curl http://127.0.0.1:9200/_cluster/health
```

## Optional Troubleshooting Exposure Mode

If you need temporary remote access to Kibana, MinIO, or Elasticsearch, set:

```dotenv
STUDYVAULT_ADMIN_BIND_ADDRESS=0.0.0.0
```

Then restart the stack:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down
docker compose -f infra/docker/compose/docker-compose.yml up -d
```

When you finish debugging, set `STUDYVAULT_ADMIN_BIND_ADDRESS` back to `127.0.0.1` and restart again. Do not leave those helper ports internet-exposed longer than necessary.

## Day-2 Operations

Pull the latest code and rebuild:

```bash
cd ~/nuiks
git pull
cd StudyVault
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

Inspect running services:

```bash
docker compose -f infra/docker/compose/docker-compose.yml ps
docker compose -f infra/docker/compose/docker-compose.yml logs --tail=100
```

Inspect one service:

```bash
docker compose -f infra/docker/compose/docker-compose.yml logs gateway --tail=100
docker compose -f infra/docker/compose/docker-compose.yml logs keycloak --tail=100
```

For additional validation beyond deployment checks, use the commands in [../tests/README.md](../tests/README.md).

Stop the stack without deleting volumes:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down
```

Delete the stack and persistent data:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down -v
```

## Recovery Notes

If login redirects are wrong, the first thing to check is `STUDYVAULT_PUBLIC_BASE_URL` in `.env`. After changing it, restart the stack so Keycloak re-renders the import file.

If an old Keycloak or database volume preserves stale state after a URL change, remove volumes and let the stack re-bootstrap:

```bash
docker compose -f infra/docker/compose/docker-compose.yml down -v
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

If Docker Compose reports permission errors, the current shell usually is not in the `docker` group yet. Open a new shell or use `sudo docker compose ...`.
