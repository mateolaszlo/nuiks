# Cloudflare Deployment Notes

StudyVault does not automate Cloudflare setup in local development. The full public-host deployment checklist now lives in `deployment.md`.

Use this short Cloudflare-only summary together with the full deployment guide:

1. Point the StudyVault domain or subdomain to the public VM through a proxied `A` record.
2. Set `STUDYVAULT_PUBLIC_BASE_URL` in `.env` to the final `https://` hostname.
3. Keep the app gateway reachable on origin port `8080`.
4. Use Cloudflare SSL/TLS mode `Flexible` unless you add separate origin-side TLS termination.
5. Keep admin and data ports bound to `127.0.0.1` unless you are temporarily troubleshooting.
6. Browse the app through the Cloudflare-backed `https://` hostname, not the raw VPS IP or `:8080`, because Keycloak PKCE and secure-context auth bootstrap depend on the browser-facing HTTPS origin.
7. The nginx gateway derives `X-Forwarded-Proto` from Cloudflare headers so Keycloak still sees HTTPS even though the origin hop remains plain HTTP on port `8080`.
8. The nginx gateway restores the real client IP from `CF-Connecting-IP` only for trusted Cloudflare proxy ranges, so nginx rate limits continue to apply per visitor instead of per Cloudflare edge address.
9. When Cloudflare publishes new proxy ranges, refresh `infra/nginx/cloudflare-realip.conf` so the trust list stays current.

Local Docker Compose validation does not require a Cloudflare account or any real DNS records.
