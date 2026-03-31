# Cloudflare Deployment Notes

StudyVault does not automate Cloudflare setup in local development. For the MVP presentation, Cloudflare is satisfied by placing the deployed StudyVault domain behind Cloudflare DNS and TLS.

Use this minimum production checklist:

1. Point the StudyVault domain or subdomain to the public gateway host through Cloudflare DNS.
2. Keep Cloudflare proxying enabled so TLS termination and basic traffic shielding remain active.
3. Forward HTTPS traffic from Cloudflare to the gateway or reverse proxy that serves the frontend and `/api/*`.
4. Preserve the Keycloak callback URL and frontend origin so they match the public hostname.

Local Docker Compose validation does not require a Cloudflare account or any real DNS records.
