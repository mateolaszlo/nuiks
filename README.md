# NUIKS-Načrtovanje in upravljanje informacijsko-komunikacijskih sistemov

## StudyVault

StudyVault is a full-stack file management demo built from a React frontend, an nginx gateway, four FastAPI services, Keycloak authentication, PostgreSQL, MongoDB, MinIO, Elasticsearch, Logstash, Kibana, and Metricbeat. The current product includes Drive-style file and folder management and versioned public APIs under `/api/v1/...`.

Use these documents as the entrypoint:

- [StudyVault overview](StudyVault/README.md)
- [Full deployment guide](StudyVault/docs/deployment.md)
- [StudyVault documentation index](StudyVault/docs/README.md)

## Fast Paths

For a local deployment:

```bash
git clone https://github.com/mateolaszlo/nuiks.git
cd nuiks/StudyVault
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose -f infra/docker/compose/docker-compose.yml up -d --build
```

For a public VM behind Cloudflare, follow the complete checklist in [deployment.md](StudyVault/docs/deployment.md). The short version is:

```bash
git clone https://github.com/mateolaszlo/nuiks.git
cd nuiks/StudyVault
cp .env.example .env
```

Then set `STUDYVAULT_PUBLIC_BASE_URL` to your public hostname, keep `STUDYVAULT_ADMIN_BIND_ADDRESS=127.0.0.1`, and start the stack with Docker Compose. The detailed guide covers Cloudflare DNS, local IP discovery, firewall expectations, validation URLs, and recovery commands.
