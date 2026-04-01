# Frontend

StudyVault uses a Vite + React + TypeScript frontend.

## Current Behavior

- unauthenticated users can sign in or create a new account through Keycloak
- normal users land on a personal dashboard for upload, file listing, search, activity, and download
- users with the `studyvault_admin` realm role land on a separate admin console

## Auth

The frontend uses `keycloak-js` and is configured for the local gateway origin:

- URL: `http://localhost:8080`
- realm: `studyvault`
- client: `studyvault-frontend`

## Scripts

```bash
npm run dev
npm run build
npm run typecheck
npm run preview
npm run test:e2e
```

`test:e2e` uses Playwright and requires Node 18+.

## Main Source Areas

- `src/App.tsx` main user and admin UI
- `src/api/` gateway-facing API client and shared response types
- `src/auth/` Keycloak login, registration, logout, and role detection
- `src/styles/` shared page styling
- `tests/e2e/` Playwright browser coverage
