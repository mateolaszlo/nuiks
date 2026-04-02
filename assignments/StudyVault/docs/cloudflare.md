# Cloudflare Deployment Notes

StudyVault does not automate Cloudflare setup in local development. The full public-host deployment checklist now lives in `deployment.md`.

Use this short Cloudflare-only summary together with the full deployment guide:

1. Point the StudyVault domain or subdomain to the public VM through a proxied `A` record.
2. Set `STUDYVAULT_PUBLIC_BASE_URL` in `.env` to the final `https://` hostname.
3. Keep the app gateway reachable on origin port `8080`.
4. Use Cloudflare SSL/TLS mode `Flexible` unless you add separate origin-side TLS termination.
5. Keep admin and data ports bound to `127.0.0.1` unless you are temporarily troubleshooting.

Local Docker Compose validation does not require a Cloudflare account or any real DNS records.
