# Frontend

StudyVault uses a Vite + React + TypeScript frontend.

## Current Behavior

- unauthenticated users can sign in or create a new account through Keycloak
- normal users land on a Drive-style workspace for folders, file uploads, search, activity, trash, and download
- users with the `studyvault_admin` realm role land on a separate admin console

## Drive UX

- the main Drive view is grid-based and uses single-select tiles
- single click selects a file or folder and opens the right-side details panel
- double click opens a folder and refreshes the breadcrumbs
- the sidebar can collapse without hiding Drive actions such as Trash and upload
- the search results surface stays hidden until search mode is active
- Trash remains a dedicated view
- long names are truncated in the grid but remain available through the tile tooltip and details panel
- the top-bar `Activity` action swaps the right-side panel from details to recent activity until a new selection overrides it

## Upload Behavior

- the file picker accepts multiple files and feeds a shared upload queue
- each queue entry tracks `queued`, `uploading`, `processing`, `done`, or `failed`
- the UI shows per-file progress while bytes upload and switches to `Processing…` until `/api/v1/files` resolves
- successful entries auto-dismiss after completion
- failed entries stay visible with `Retry` and `Dismiss` actions
- users can drop external files onto the current Drive surface, a folder tile, or a breadcrumb destination
- upload destinations are captured when the queue item is created so later navigation does not retarget in-flight work

## Error Handling

- create-folder, rename, and move conflicts stay local to the relevant Drive form
- upload and search failures stay near the affected UI surface unless recovery requires a broader state change
- auth/session failures such as missing or invalid bearer tokens push the app into a relogin-oriented recovery state
- the frontend parses structured API error responses, including categories, stable codes, and optional field errors

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
