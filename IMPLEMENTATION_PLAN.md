# IMPLEMENTATION_PLAN.md

# StudyVault: Google Drive Clone Implementation Plan

## Document status

- **Target repo:** `mateolaszlo/nuiks` → `assignments/StudyVault`
- **Goal:** evolve the current StudyVault from a flat personal file vault into a single-user, Google Drive–style file manager
- **Included in scope:** folders, nested navigation, rename, move, trash, restore, 30-day retention purge, external file drag-and-drop upload, queued uploads, per-file upload progress
- **Development assumption:** this repo is still pre-release, runs mainly in Docker, and development/test data can be reset when schema changes require it

---

## 1. Executive summary

StudyVault already has the major platform pieces needed for a Drive-like personal file manager:

- React frontend
- nginx gateway
- `file-service` for upload/download orchestration
- `catalog-service` as canonical metadata in PostgreSQL
- `search-service` as searchable metadata in MongoDB
- `activity-service` as user event history in MongoDB
- MinIO as object storage
- Keycloak-based authentication

This means the feature does **not** require a rewrite, but it **does** require a meaningful domain-model expansion.

For the next UX step — drag files from the desktop into the browser and show Google Drive–style upload progress — the repo is also in a good position. The existing backend already accepts one multipart upload per request and already accepts `parent_folder_id`. That means the missing pieces are primarily in the frontend: external drop handling, a client-side upload queue, and an upload transport that can surface progress events.

The most important architectural decision in this plan is:

> **Keep file bytes in MinIO exactly as they are, and implement Drive semantics in metadata.**

That keeps object storage simple and makes rename/move fast and cheap.

### Pre-release implementation stance

Because this project is still unreleased and local/test environments are disposable:

- prefer **clean schema evolution** over complex rollout choreography
- prefer **reset/recreate** over backward-compatibility layers when a phase changes the schema substantially
- keep compatibility shims only when they materially reduce implementation risk during the current phase
- optimize for incremental delivery and reliable tests, not zero-downtime migration behavior

---

## 2. Product scope

### 2.1 In scope

Users can:

- create folders at root or inside other folders
- rename folders
- move folders
- delete folders to trash
- restore folders from trash
- upload files into a selected folder
- drag files from the operating system file explorer into the current Drive view to start upload automatically
- drag files from the operating system file explorer onto a folder tile to upload directly into that folder
- select or drop multiple files and queue them for upload
- see per-file upload status (`queued`, `uploading`, `processing`, `done`, `failed`)
- retry failed uploads from the queue
- rename files
- move files
- delete files to trash
- restore files from trash
- browse folders with breadcrumbs
- view trash
- permanently lose trashed items after 30 days

### 2.2 Out of scope

Do **not** implement in this phase:

- any form of file sharing
- user-to-user access permissions
- public links
- file comments
- previews/editors
- real-time collaboration
- file version history
- recovery beyond 30 days
- quota/billing
- drag-and-drop of directories/folders from the operating system in this phase
- resumable uploads or background uploads that survive page refresh
- true Google Drive–style cross-session upload persistence
- per-file tag editing inside the queue in this phase



## 3. Error handling and consistency model

## 3.1 What is authoritative?

Catalog-service / PostgreSQL is authoritative.

Search-service and activity-service are derived systems.

### Rule

If search or activity is temporarily inconsistent, catalog data wins.

This should also be reflected in operational tooling.

### 3.2 Upload queue authority and progress semantics

Catalog-service / PostgreSQL remains authoritative for completed uploads.

The browser is authoritative only for transient upload queue state before the API request finishes.

That means:

- `queued` means the file exists only in frontend state and no request has started yet
- `uploading` means bytes are currently moving from browser to nginx/file-service
- `processing` means the browser has sent all bytes, but the server has not yet returned success because `file-service` is still storing the object and publishing to catalog/search/activity
- `done` means the upload request returned success and the normal folder reload can treat the item as persisted
- `failed` means the request failed or was aborted and the queue entry should stay visible until the user retries or dismisses it

Important UI rule:

> **100% uploaded does not mean fully complete yet. Show `Processing…` until the `/api/files` request resolves successfully.**

This matters in this repository because `apps/file-service/app/services/files.py` performs downstream synchronization after the object bytes are accepted.

---

## 4. Testing plan

## 4.1 Unit tests

### Shared validation

- valid folder names
- invalid folder names
- normalization rules
- restore destination resolution
- upload queue state transitions (`queued` → `uploading` → `processing` → `done` / `failed`)
- enqueue destination snapshot logic
- dropped external files are classified differently from internal item move drag state

### Catalog-service

- create folder at root
- create nested folder
- reject duplicate sibling name
- keep committed folder creation successful even if post-persist search indexing fails
- move folder to root
- reject move into self
- reject move into descendant
- trash folder cascade
- restore folder to original parent
- restore folder to root fallback
- conflict on restore with same-name sibling

### File-service

- upload into folder
- keep upload success tied to object storage plus catalog persistence, while tolerating post-persist search or activity fanout failures
- rename file
- move file
- trash file
- restore file
- hard delete file deletes object store entry
- repeated queued uploads still publish the same metadata/search/activity side effects as single manual uploads

### Search-service

- index file
- index folder
- search excludes trashed items by default
- search includes trashed when requested

### Activity-service

- accepts generic activity event
- message mapping remains correct

## 4.2 API/integration tests

- create folder → upload file into folder → list folder contents
- repeated single-file uploads (as executed by the frontend queue) into the same folder
- nested folder navigation
- file move between folders
- folder move between folders
- folder trash cascade updates descendants
- restore after original parent removal falls back to root
- purge worker deletes expired items

### Completed in this run

- added `apps/purge-worker/Dockerfile` so the existing purge worker can run as its own Python container
- added `purge-worker` to `infra/docker/compose/docker-compose.yml` as an internal-only service
- configured Compose defaults for hourly purge execution with `PURGE_RUN_MODE=loop` and `PURGE_INTERVAL_SECONDS=3600`
- verified the worker remains unexposed to the host and uses internal URLs for catalog, file, and search calls
- added Compose smoke coverage for the new worker service and its schedule-related environment wiring
- switched pytest test environment bootstrapping to read `StudyVault/.env.test` directly, so the tracked env fixture is now the single source of truth for fake-host test settings
- updated backend public-token validation to enforce issuer, accept the frontend client through `aud` or `azp`, and log safe auth-mismatch diagnostics without logging raw tokens
- added a Keycloak audience mapper for the `studyvault-frontend` client so newly registered users receive compatible access tokens
- aligned activity-service and auth unit tests with the stricter token-claim requirements introduced by the new validation rules
- replaced the static nginx gateway config with an env-rendered template and exposed auth, upload, search, and admin rate/burst settings through `.env`
- raised the default admin-panel gateway rate limits so repeated enable/disable and password-reset actions do not trip normal `429` throttling

## 4.3 Frontend E2E tests

Using Playwright:

- capture and reuse authenticated storage state for seeded `demo` and `admin` users so the suite does not repeatedly hit gateway auth throttles
- create folder from root
- navigate with breadcrumbs
- upload file into current folder
- select multiple files in the picker and confirm they enter a visible queue
- drag a file from the desktop onto the current Drive surface and confirm upload starts automatically
- drag a file from the desktop onto a folder tile and confirm it lands in that folder
- confirm upload progress reaches `Uploading` and then `Processing` before success
- confirm a failed upload remains in the queue with retry/dismiss actions
- rename file
- move file
- trash file
- restore file from trash
- trash folder with children
- search folder and file results
- select a file tile and show its details in the right-side panel
- select a folder tile and show its details in the right-side panel
- double click a folder tile to open it
- verify single click no longer opens folders
- click `Activity` in the top bar and show the activity panel
- select an item while activity is open and switch the panel to details
- use context menu `Info` to open the same details panel
- confirm drag-and-drop into folder tiles still works in grid layout
- confirm `Search Results` and `Trash` remain list-based in this phase

## 4.4 Docker/test environment rule

If a test run requires `docker compose` or local service startup:

- start only what is needed
- run the relevant tests
- always shut services down after tests finish, whether they pass or fail

This should be treated as mandatory cleanup, especially for Codex-driven iterative development.

---

## 5. Edge cases and policy decisions

These should be explicitly agreed before implementation to avoid churn.

### 5.1 Name conflicts on restore

**Recommendation:** return `409 Conflict` and let the user resolve it.

### 5.2 Restore when original parent is unavailable

**Recommendation:** restore to root and inform the UI.

### 5.3 Folder delete behavior

**Recommendation:** cascade soft-delete descendants immediately.

### 5.4 Empty folders

Allowed.

### 5.5 Search behavior

**Recommendation:** normal search excludes trashed items by default.

### 5.6 Downloading trashed files

**Recommendation:** disallow normal download of trashed items unless explicitly restored first.

### 5.7 Hard delete from UI

Optional.

For MVP, it is acceptable to show only restore in the trash UI and rely on automatic purge. Adding “Delete forever” is a nice enhancement but not required.

### 5.8 Main Drive layout scope

**Decision:** apply grid layout only to the main `My Drive` browser in this phase.

### 5.9 Selection model

**Decision:** allow only single selection.

### 5.10 Folder open interaction

**Decision:** folders open on double click, not single click.

### 5.11 Right-side panel precedence

**Decision:** the shared right-side panel shows either details or activity, never both at once. Item selection overrides activity view.

### 5.12 Item metadata visibility

**Decision:** item metadata moves out of the main grid and into the details panel. The grid shows only minimal item identity.

### 5.13 External file drag-and-drop classification

**Decision:** when `event.dataTransfer.files` is non-empty and no internal `draggedItem` is active, treat the interaction as an upload, not a move.

This is required so new desktop-to-browser uploads do not break the existing in-app drag-and-drop move behavior.

### 5.14 Upload destination rule

**Decision:** dropping onto the main drive surface uploads into `currentFolderId`; dropping onto a folder tile uploads into that folder; dropping onto a breadcrumb uploads into that breadcrumb folder.

### 5.15 Queue destination snapshot

**Decision:** capture `parent_folder_id` and tag input at enqueue time, not when the request finally starts.

Otherwise a user could change folders while files are still queued and accidentally upload files into the wrong destination.

### 5.16 Upload progress wording

**Decision:** use five visible statuses: `Queued`, `Uploading`, `Processing`, `Done`, `Failed`.

`Processing` is mandatory because the current backend finishes catalog/search/activity work after the browser has finished sending bytes.

### 5.17 Failed upload behavior

**Decision:** keep failed entries visible in the queue and allow `Retry` and `Dismiss`.

### 5.18 Queue concurrency

**Decision:** start with a small fixed concurrency limit of `2`.

That is enough to feel responsive, but conservative for the current Docker-first stack and simpler than fully parallel uploads.

### 5.19 File picker behavior

**Decision:** the sidebar file input should accept multiple files and enqueue immediately after selection or explicit submit, depending on the chosen UI wiring. The plan below assumes explicit submit remains available for parity with the current form.

### 5.20 Dropped operating-system folders

**Decision:** out of scope for this phase. Accept only regular files from the browser `FileList`.

### 5.21 Public API versioning

**Decision:** public HTTP endpoints are versioned under `/api/v1/...` only. Unversioned `/api/...` paths are removed. Internal routes remain under `/internal/...` and health checks remain under `/health`.

---

## 6. Repo-level task list

## 6.1 `packages/backend-common`

- [x] Add `FolderRecord`
- [x] Add `DriveItem`
- [x] Add folder DTOs
- [x] Add generic activity DTOs
- [x] Add name validation helpers
- [x] Extend `FileRecord` with folder/trash metadata

## 6.2 `apps/catalog-service`

- [x] Add schema change for `folders`
- [x] Add new `files` columns
- [x] Add folder repository methods
- [x] Add folder fetch endpoint
- [x] Add item listing endpoint
- [x] Add breadcrumbs endpoint
- [x] Add trash list endpoint
- [x] Add create folder endpoint
- [x] Add rename folder endpoint
- [x] Add trash folder endpoint
- [x] Add move folder endpoint
- [x] Add restore logic
- [x] Add expired-trash internal endpoint
- [x] Add internal file patch endpoint
- [x] Add internal file move endpoint
- [x] Add internal file trash endpoint
- [x] Add internal file restore endpoint
- [x] Add internal file hard-delete endpoint
- [x] Add internal folder hard-delete endpoint
- [x] Add internal catalog export route
- [x] Keep folder create responses successful after the folder is persisted even if search publication fails

## 6.3 `apps/file-service`

- [x] Extend upload request to accept `parent_folder_id`
- [x] Add rename file endpoint
- [x] Add move file endpoint
- [x] Add trash file endpoint
- [x] Add restore file endpoint
- [x] Add hard delete method for purge worker
- [x] Add `delete()` to object store abstraction
- [x] Keep the existing single-file `/api/files` contract as the backend primitive for queued uploads
- [x] Document in code/comments that upload completion happens only after downstream sync, so frontend `processing` state is expected
- [x] Keep upload success dependent on catalog persistence, while treating post-persist search and activity fanout as best effort

## 6.4 `apps/search-service`

- [x] Hide trashed files by default
- [x] Replace file-only index doc with item index doc
- [x] Add folder indexing
- [x] Add delete by `item_id`
- [x] Add filters for trashed and kind
- [x] Expose mixed public search results
- [x] Add reindex script

## 6.5 `apps/activity-service`

- [x] Replace upload-only activity model
- [x] Accept generic item events
- [x] Update activity message mapping

## 6.6 `apps/frontend`

- [x] Replace flat file list with folder browser
- [x] Add breadcrumbs
- [x] Add create folder UI
- [x] Add rename UI
- [x] Add move UI
- [x] Add trash page
- [x] Update search results to support folders
- [x] Replace the main `My Drive` list view with a Google Drive-style responsive grid
- [x] Show only file/folder name and kind in grid tiles
- [x] Add single-selection state for current Drive items
- [x] Open selected item details in the right-side panel
- [x] Change folder navigation from single click to double click
- [x] Add topbar `Activity` button and move activity feed into the right-side panel
- [x] Hide the right-side panel when no item is selected and activity is closed
- [x] Add `Info` action to the file/folder context menu
- [x] Keep drag-and-drop move working with folder tiles
- [x] Keep `Search` and `Trash` as list views in this phase
- [x] Keep folder navigation usable during the transition away from single-click open
- [x] Hide `Search Results` when not in search mode
- [x] Move `New Folder` into the `My Drive` action row
- [x] Add collapsible Drive sidebar with icon-only collapsed rail
- [x] Handle excessively long file/folder names in the grid and details view
- [x] Replace single-file sidebar upload state with queue-based state
- [x] Accept multiple files from the sidebar file input
- [x] Add a shared enqueue helper for both file input selection and external dropped files
- [x] Add external file drag-and-drop upload on the current drive surface
- [x] Preserve internal drag-and-drop move behavior while external upload is added on the main drive surface
- [x] Add external file drag-and-drop upload onto folder tiles and breadcrumbs
- [x] Add per-file upload progress UI with `Queued`, `Uploading`, `Processing`, `Done`, and `Failed` states
- [x] Keep failed uploads retryable from the queue
- [x] Add a dedicated upload method in `api/client.ts` that uses `XMLHttpRequest`
- [x] Add a small upload scheduler that runs at most two active uploads at once
- [x] Reduce reliance on global `isBusy` during upload queue execution
- [x] Prevent default browser file-open behavior during external drag-and-drop over the Drive app
- [x] Auto-dismiss successful upload queue entries after a short delay
- [x] Delay `Processing…` until the browser has actually completed the upload phase
- [x] Reuse Playwright auth state for seeded users so browser E2E coverage avoids repeated auth throttling

### 6.6.1 Drive browser UX refresh

The current Drive browser shows a vertical list with inline metadata and opens folders on single click. This phase changes the main `My Drive` view to behave more like Google Drive.

#### Goals

- make the main browser visually scan like a grid of items instead of a table
- reduce clutter by moving metadata out of the main surface
- support selection-first interaction with a contextual info panel
- keep existing backend APIs and file/folder operations intact
- hide the breadcrumb row at Drive root; use the `My Drive` heading as the root location indicator

#### Main view behavior

- apply the new layout only to the main `My Drive` browser
- do not change `Search Results` or `Trash` in this phase
- render files and folders as responsive tiles
- each tile displays item name and a visual file/folder distinction
- do not display path, size, tags, created time, updated time, or row hints inline in the grid

#### Selection behavior

- single click selects one item
- selecting an item opens the right-side details panel
- only one item can be selected at a time
- selecting a new item replaces the current selection
- selection is cleared when entering another folder, refreshing folder contents, switching to trash, or after destructive actions remove the selected item from view

#### Open behavior

- double click on a folder opens that folder
- single click on a folder only selects it
- double click on a file does nothing in this phase
- breadcrumb navigation remains unchanged

#### Right-side panel behavior

The right-side column becomes a shared contextual panel with three states:

- hidden
- details
- activity

Rules:

- if the user selects an item, show `details`
- if the user clicks the topbar `Activity` button, show `activity`
- if neither is active, hide the panel
- selection takes precedence over activity
- clicking `Activity` while details are open switches the panel to activity
- selecting an item while activity is open switches the panel to details

### 6.6.2 Drive workspace polish

- hide the upper `Search Results` surface until the user submits a non-empty search
- move `New Folder` into the `My Drive` action row beside navigation actions
- allow the Drive sidebar to collapse into an icon-only rail
- keep long file and folder names clamped by default, reveal more on hover/focus, and preserve the full name in details view/tooltips

#### Details panel contents

For the selected file or folder, show:

- name
- kind
- full path derived from breadcrumbs plus item name
- size for files
- mime type for files when present
- tags
- created time
- updated time

Folder-specific display:

- show folder as kind `Folder`
- no file size value is required for folders

#### Context menu changes

Keep existing actions:

- Open or Download
- Rename
- Move to…
- Move to Trash

Add:

- Info

`Info` behavior:

- closes the context menu
- selects the clicked item
- opens the right-side details panel for that item

#### Editing actions

- keep rename and move functionality
- remove inline rename/move editors from item tiles
- expose rename and move through the existing context menu or overflow actions
- render rename and move UI outside the grid so tile layout remains stable

#### Layout expectations

- preserve drag-and-drop support for moving items into folders
- selected tile must have a clear selected state
- hover, selected, and drop-target states must be visually distinct
- avoid horizontal overflow on desktop and mobile
- on narrower screens, stack or reposition the contextual panel below the main content if needed

### 6.6.3 External drag-and-drop upload, queue, and progress

The current frontend already has in-app drag-and-drop for moving `DriveItem` records between folders and trash. That behavior is implemented in `assignments/StudyVault/apps/frontend/src/App.tsx` with `draggedItem` and `activeDropTarget`.

The remaining upload work is now limited to external drag-and-drop. The queue foundation already exists:

- sidebar form stores multiple pending files before enqueue
- `handleUpload()` adds queue entries with destination and tag snapshots
- `ApiClient.uploadFileWithProgress()` in `assignments/StudyVault/apps/frontend/src/api/client.ts` now uses `XMLHttpRequest`
- external drag-and-drop still needs to feed that same queue/transport path

Because of that, implement the next upload UX phase as a frontend refactor, not a backend rewrite.

#### Required frontend changes

- [x] Replace `selectedFile: File | null` with an upload queue collection that can hold many pending files
- [x] Introduce an `UploadQueueItem` model with at least: local id, `File`, destination folder id, tags snapshot, status, progress percent, server file id (optional), and error message
- [x] Add a dedicated upload method in `assignments/StudyVault/apps/frontend/src/api/client.ts` that uses `XMLHttpRequest` so `xhr.upload.onprogress` can update the queue
- [x] Keep the existing generic `request()` helper for non-upload API calls
- [x] Add a shared enqueue helper for both file input selection and external drag-and-drop
- [x] Add a small upload scheduler that runs at most two active uploads at once
- [x] On each success, update the queue entry to `done` and refresh the visible folder contents when appropriate
- [x] On each failure, update the queue entry to `failed` without discarding it
- [x] Add `Retry` and `Dismiss` actions for failed entries
- [x] Reduce reliance on global `isBusy` so browsing, selection, and search are not frozen for the full duration of a multi-file upload batch

#### External drag-and-drop surfaces

Handle operating-system file drops in these places:

- [x] the main drive content surface for upload into the current folder
- [x] folder tiles for upload directly into that folder
- [x] breadcrumb buttons for upload into an ancestor folder
- [x] consume handled folder-target external drops so they do not bubble and enqueue duplicate uploads into the current folder

Use this rule in `App.tsx`:

- if `draggedItem` is set, treat drag/drop as an internal move
- else if `event.dataTransfer.files.length > 0`, treat drag/drop as an external upload

This preserves the existing internal move semantics while enabling desktop file drops.

#### Queue UI behavior

Add a visible queue panel directly below the `My Drive` header. Each row should show:

- file name
- destination label
- status text
- progress bar for `uploading`
- `Processing…` indicator after bytes reach 100% but before the API resolves
- retry/dismiss controls for failed items

The queue should be visible even after the sidebar file input is cleared so the user can watch batch progress.

#### Suggested file-level edits

`assignments/StudyVault/apps/frontend/src/api/client.ts`

- add a specialized upload function such as `uploadFileWithProgress(...)`
- accept callbacks or an observer object for `onProgress`, `onSuccess`, `onError`, and optional `signal`/abort handling
- keep request authentication consistent by reusing `getToken()`

`assignments/StudyVault/apps/frontend/src/App.tsx`

- add queue state and queue-processing logic
- add external drag-enter / drag-over / drag-leave / drop handlers
- add an overlay or highlight state so the current drop target is obvious
- adapt folder-tile and breadcrumb drop handlers so they can route either move or upload behavior

`assignments/StudyVault/apps/frontend/src/styles/main.css`

- add styles for external drop highlight state
- add queue row and progress bar styles
- ensure upload feedback works in both expanded and collapsed sidebar layouts

`assignments/StudyVault/apps/frontend/tests/e2e/studyvault.spec.ts`

- add coverage for multi-file queueing
- add coverage for drag-dropping an external file into the current folder
- add coverage for drag-dropping an external file onto a folder tile
- add coverage for a failed upload entry and retry flow

#### Backend impact

For the first iteration, no new backend API is required. The queue should simply execute the already-existing `/api/files` upload request once per file.

Future optimization path, explicitly out of scope here:

- direct-to-object-store multipart uploads
- resumable uploads
- batch upload session APIs

## 6.7 New worker or command

- [x] Add purge worker command
- [x] Process expired files
- [x] Process expired folders
- [x] Add batch processing
- [x] Add retries/logging
- [x] Make schedule configurable

## 6.8 Public API versioning

- [x] Add `fastapi-versioning` to the Python requirements
- [x] Split each public service into versioned public routers and unversioned internal routes
- [x] Serve public endpoints under `/api/v1/...` in catalog, file, search, and activity services
- [x] Keep `/internal/...` routes unversioned
- [x] Keep `/health` unversioned
- [x] Update nginx public gateway routing to `/api/v1/...`
- [x] Update frontend API callers to `/api/v1/...`
- [x] Update public downstream service callers to `/api/v1/...`
- [x] Update smoke/runtime checks and relevant frontend/service tests for `/api/v1/...`
- [x] Add representative checks that old unversioned public paths no longer work

### 6.8.1 FastAPI versioning migration

This phase moves the public StudyVault HTTP surface from ad hoc `/api/...` routing to explicit versioned routes using `fastapi-versioning`.

Scope:

- public endpoints for `catalog-service`, `file-service`, `search-service`, and `activity-service`
- nginx gateway forwarding for those public endpoints
- frontend callers and runtime smoke coverage

Non-scope:

- `/internal/...` service routes
- `/health` endpoints
- any multi-version compatibility layer beyond `v1`

Resulting contract:

- public routes are served from `/api/v1/...`
- old unversioned public `/api/...` routes return `404`
- internal service-to-service routes remain under `/internal/...`
- health checks remain under `/health`

## 6.9 Error handling and recovery UX

- [x] Add a shared structured error response model in `packages/backend-common`
- [x] Route new shared `StudyVaultHTTPException` responses through the structured error shape
- [x] Preserve structured downstream error details across service-to-service HTTP calls
- [x] Normalize catalog/file conflict responses for create, rename, move, and restore flows to stable error codes
- [x] Improve conflict detail messages to include item name and target location where available
- [x] Parse structured API errors in the frontend client instead of throwing raw text only
- [x] Render create-folder, rename, and move failures inline near the failing Drive action instead of only using the global banner
- [x] Extend structured error codes and recovery UX to upload flows
- [x] Extend structured error codes and recovery UX to search flows
- [x] Extend structured error codes and recovery UX to auth/session flows
- [x] Add admin error display improvements for stable error codes and safe structured context

### 6.9.1 First implementation slice

This first slice focuses on the most common Drive interaction failures where users currently get generic or ambiguous responses.

Implemented in this slice:

- shared JSON error responses now include `detail`, `code`, `category`, `recoverable`, and optional `context`
- `catalog-service` and `file-service` now emit stable conflict codes for folder/file create, rename, move, and restore conflicts
- duplicate-name conflict messages now identify the conflicting item type and destination location
- the frontend API client now parses structured API failures into a typed error object
- Drive create-folder, rename, and move forms now keep the UI open and render the failure locally instead of surfacing everything through the page-wide error banner

Deferred to later error-handling slices:

- upload/search/auth/admin-specific recovery UX
- structured field validation rendering
- richer admin error-code summaries and correlation-friendly diagnostics in the admin panel

### 6.9.2 Upload, search, and auth recovery

This slice extends the structured error contract and local recovery behavior beyond Drive create/rename/move.

Implemented in this slice:

- upload validation and downstream sync failures now use structured public error codes instead of plain FastAPI `detail` strings
- search query validation now returns structured validation errors instead of the default raw FastAPI 422 payload
- public auth failures now return structured auth or permission codes such as missing bearer token, invalid token, unknown signing key, and admin access required
- upload and search failures now render near the failing UI surface instead of escalating to the page-wide banner by default
- auth/session failures during authenticated API calls now transition the app back to a relogin-oriented state rather than leaving the user in a broken workspace
- admin dashboard refresh and user-management actions now keep partial data visible, render per-section/admin-action error messages locally, and only expose a safe subset of structured error context

Deferred to the next slice:

- richer admin UI summaries of operational errors

## 6.10 Documentation refresh

- [x] Refresh top-level StudyVault product docs after Drive UX and API-versioning changes
- [x] Refresh frontend and service READMEs for current behavior and endpoints
- [x] Refresh shared/backend docs for structured errors and auth/error contracts
- [x] Refresh deployment and docs index pages for the top-level `StudyVault/` layout and current validation workflow
- [x] Verify markdown examples and commands against the current repo layout, `/api/v1` paths, and current test commands

## 6.11 Security hardening

- [x] Enforce JWT audience validation for all public `/api/v1/...` routes
- [x] Stop passing `audience=None` for normal public route authentication
- [x] Use the intended frontend client audience for browser-issued access tokens
- [x] Keep internal `/internal/...` routes on their existing internal-token model
- [x] Reject tokens with missing or mismatched audience claims as unauthorized
- [x] Add a browser-facing security header baseline at the nginx gateway
- [x] Add `Content-Security-Policy` for the current same-origin frontend and proxied Keycloak paths
- [x] Add `X-Content-Type-Options: nosniff`
- [x] Add `Referrer-Policy: strict-origin-when-cross-origin`
- [x] Add `Permissions-Policy`
- [x] Add `Strict-Transport-Security` only when the effective public request scheme is HTTPS
- [x] Stop trusting uploaded MIME metadata as the download response `media_type`
- [x] Serve downloads as `application/octet-stream` while keeping `Content-Disposition: attachment`
- [x] Keep stored MIME metadata only for metadata/search/display use, not browser execution type
- [x] Add explicit host allowlisting for public requests
- [x] Add explicit CORS policy that preserves the current same-origin architecture
- [x] Keep cross-origin browser access denied by default unless the configured public origin is explicitly needed
- [x] Add first-pass request throttling for abuse-prone public endpoints
- [x] Cover at least `/realms/`, `/api/v1/files`, `/api/v1/search`, and `/api/v1/admin/`
- [x] Keep the first rate-limit phase nginx-based and per-IP rather than introducing distributed quota state
- [x] Add regression tests for JWT audience enforcement, browser security headers, safer downloads, host/CORS policy, and throttling configuration

### 6.11.1 JWT audience enforcement

- [x] Update the shared auth helper so public API JWT validation requires an expected audience
- [x] Add a shared auth setting for the expected public token audience if one is not already exposed cleanly
- [x] Default the public audience to `studyvault-frontend` unless a stronger repo-wide auth setting is introduced
- [x] Update file-service public routes to require the public audience
- [x] Update catalog-service public routes to require the public audience
- [x] Update search-service public routes to require the public audience
- [x] Update activity-service public routes to require the public audience
- [x] Keep issuer, signature, and algorithm validation unchanged
- [x] Return stable `401` structured auth errors for wrong-audience tokens

### 6.11.2 Browser response hardening

- [x] Add a CSP that works with the current frontend assets, Keycloak login pages, and proxied static resources
- [x] Validate the CSP against `/`, `/realms/`, `/resources/`, and current frontend asset loading before considering the header complete
- [x] Add `nosniff` at the gateway for browser-facing responses
- [x] Add anti-framing protection at the gateway
- [x] Use `X-Frame-Options: SAMEORIGIN` until a stricter CSP-compatible framing policy can replace it without breaking silent SSO
- [x] Add a referrer policy at the gateway
- [x] Add a permissions policy at the gateway
- [x] Emit HSTS only when the effective forwarded scheme is HTTPS

### 6.11.3 Download content-type hardening

- [x] Change file download responses to use `application/octet-stream` by default
- [x] Preserve attachment download behavior with `Content-Disposition`
- [x] Do not allow user-controlled upload MIME metadata to become the browser execution type on download
- [x] Keep MIME metadata available for non-execution uses if needed by search/details UI
- [x] Pair the download hardening with `X-Content-Type-Options: nosniff`

### 6.11.4 Host and CORS hardening

- [x] Add explicit trusted-host handling for the configured public hostname
- [x] Allow `localhost` and `127.0.0.1` for container-local `/health` probes without relaxing public host validation
- [x] Allow first-party Docker Compose service hostnames and host:port pairs for internal service-to-service HTTP calls and admin health probes
- [x] Reject unexpected host headers instead of relying on implicit proxy behavior
- [x] Add explicit CORS behavior instead of relying on the absence of permissive headers
- [x] Keep default behavior same-origin and deny arbitrary cross-origin access
- [x] If browser CORS is required for any public path, allow only the configured public origin

### 6.11.5 Rate limiting and abuse controls

- [x] Add nginx rate-limit zones for public traffic
- [x] Apply a conservative per-IP throttle to Keycloak-adjacent auth traffic under `/realms/`
- [x] Apply a conservative per-IP throttle to uploads under `/api/v1/files`
- [x] Apply a conservative per-IP throttle to search under `/api/v1/search`
- [x] Apply a conservative per-IP throttle to admin endpoints under `/api/v1/admin/`
- [x] Keep normal single-user interactive behavior unaffected by default limits
- [x] Defer advanced per-user quotas and distributed abuse accounting to a later phase

### 6.11.6 Security regression coverage

- [x] Add auth tests proving same-realm wrong-audience tokens are rejected
- [x] Add auth tests proving correct-audience tokens still work
- [x] Add config or response tests for the gateway security headers
- [x] Add tests proving HSTS is tied to effective HTTPS requests only
- [x] Add download tests proving spoofed upload MIME types do not control download `media_type`
- [x] Add tests proving download responses remain attachments
- [x] Add tests for explicit host/CORS rejection behavior
- [x] Add regression coverage for loopback trusted hosts used by container-local health probes
- [x] Add config-level tests for nginx throttling coverage on protected routes

---

Revision note: expanded the implementation plan to cover desktop file drag-and-drop, a client-side upload queue, and Google Drive–style upload progress because the current repository already has the backend primitives and now mainly needs a frontend execution plan for the next UX phase.
Revision note: updated the plan after implementation work that made folder create and file upload resilient to post-persist downstream failures, widened trusted-host handling for internal Docker Compose service calls, and changed Playwright to reuse stored auth state for seeded users so E2E runs stop tripping gateway auth throttling.
Revision note: restored the optional bundled `local-minio` Docker profile by letting `file-service` auto-create the configured bucket only when storage reports a true missing-bucket `404`, while keeping inaccessible dedicated buckets as startup failures.
Revision note: documented the validated local Playwright flow as repo-root `local-minio` Compose startup plus `apps/frontend` test execution, and aligned GitHub Actions so only `main` runs the browser E2E path.


## 6.12 User Profile and Password Management

### Context and Policy
- **Product scope:** Add an avatar dropdown to the frontend navigation bar showing the user's name and email. Include links to Keycloak's native Account Management Console for profile edits and password changes, along with a logout action. Custom React profile forms and custom Keycloak themes are out of scope.
- **Consistency & State:** Keycloak is strictly authoritative for user data. Because the StudyVault backend ties relationships to immutable Keycloak IDs (`owner_id`), changing an email or password will not break files or database logic. To prevent the frontend from showing stale session data after an edit, the app must trigger a silent token refresh when returning from the Keycloak console.
- **Edge cases:** Historical entries in the activity logs and existing file metadata will retain denormalized usernames/emails from the time they were recorded. We accept this staleness and will not run retroactive database migrations for name changes.

### Task list

#### `apps/frontend`
- [x] Add a user avatar component to the top right of the navigation bar
- [x] Extract `name` (or `preferred_username`) and `email` from the active Keycloak JWT token
- [x] Add a clickable dropdown menu attached to the user avatar
- [x] Display the extracted user information at the top of the dropdown menu
- [x] Add a "Manage Account" link redirecting to the Keycloak account console (`/realms/studyvault/account/`)
- [x] Add a "Change Password" link redirecting to the Keycloak password update page
- [x] Add a "Logout" action that triggers the Keycloak session termination flow
- [x] Implement an automatic token refresh strategy (e.g., on window focus) to update the UI if the user altered their profile
- [x] Ensure the dropdown menu dismisses correctly when clicking outside

#### Testing
- [x] Add Playwright E2E test verifying the avatar menu displays correct token details
- [x] Add Playwright E2E test verifying "Manage Account" and "Change Password" point to the correct external URLs
- [x] Add Playwright E2E test verifying the "Logout" flow
- [x] Refresh Playwright auth/admin workspace selectors so the suite tracks the current admin UI instead of the retired `Admin Console` expectation
- [x] Relax local `.env.example` auth throttling defaults for manual testing and Playwright, and document that deployment environments should tighten them
- [x] Keep the logout E2E outside the shared seeded auth-state Drive block so later tests do not inherit a server-side terminated Keycloak session
- [ ] Manually verify that changing the user's name/email in Keycloak cleanly updates the frontend display upon returning, without requiring a hard browser refresh

## 6.13 Folder Details Expansion (Counts and Size)

### Context and Policy
- **Product scope:** When a user selects a folder and views it in the right-side details panel, the system must display the total recursive size of the folder's contents, alongside a count of active files and subfolders inside it.
- **Performance & State:** Because a folder might contain deeply nested directory trees, computing these aggregates on every normal folder list request would slow down grid navigation. Therefore, folder statistics should be queried on demand via a new dedicated endpoint, which is only called when the details panel is actively viewing that folder.
- **Edge cases:** Items that are currently in the trash must be excluded from both the file count and the total size computation to reflect only active space usage in the selected tree. 

### Task list

#### `apps/catalog-service`
- [ ] Add a repository CTE (Common Table Expression) or database query to recursively find all descendant items of a given `folder_id`
- [ ] Aggregate `total_size_bytes` for all descendant files within the tree
- [ ] Aggregate `file_count` and `folder_count` for all descendant items
- [ ] Expose a new GET endpoint at `/api/v1/folders/{folder_id}/stats` returning the computed totals
- [ ] Ensure the recursive query explicitly ignores any items where `is_trashed` / `trashed_at` is true

#### `apps/frontend`
- [ ] Add a `getFolderStats(folderId: string)` definition to `apps/frontend/src/api/client.ts`
- [ ] Update the right-side details panel component to trigger a stats fetch when the `selectedItem` is of kind `Folder`
- [ ] Add a localized loading indicator (e.g., skeleton text or a small spinner) inside the details panel while stats are being fetched
- [ ] Format and display the `total_size_bytes` using the existing human-readable size formatter
- [ ] Display the counts cleanly in the metadata block (e.g., "Contains: 42 files, 3 folders")

#### Testing
- [ ] Add `catalog-service` unit tests proving the recursive size calculation correctly sums deeply nested files
- [ ] Add `catalog-service` unit tests proving trashed descendant files and folders are excluded from stats
- [ ] Update Playwright E2E tests: select a folder with known test seed data and verify the details panel eventually renders the correct total size and item count

## 6.14 Instance Quotas and Storage Limits

### Context and Policy
- **Product scope:** Introduce basic instance-wide guardrails to prevent untethered growth. This includes a hard limit on the total number of registered users across the instance, a per-user storage quota, and a visual storage usage gauge in the left sidebar.
- **Account Limits:** Controlled via a `.env` variable (e.g., `MAX_REGISTERED_USERS=20`). Since Keycloak manages user identities directly, enforcing this requires restricting the Keycloak registration flow. If self-registration is enabled, an admin worker or custom Keycloak flow execution must track the user count and disable new registrations when the threshold is hit. 
- **Storage Quota:** Controlled via a `.env` variable (e.g., `USER_STORAGE_QUOTA_BYTES=1073741824` for 1GB). The `file-service` must validate the user's current storage total in the database before accepting new uploads.
- **Edge cases:** Trashed files still consume object storage, but for MVP quota calculations, we will count only *active* (non-trashed) files against the user's limit. If an upload exceeds the quota, it must return a `413 Payload Too Large` or `402 Payment Required` (using our shared structured error format) and abort before streaming to MinIO.

### Task list

#### `infra/` & Keycloak
- [ ] Add `MAX_REGISTERED_USERS` and `USER_STORAGE_QUOTA_BYTES` to the base `.env.example` and environment configurations
- [ ] Implement a lightweight constraint on Keycloak to enforce `MAX_REGISTERED_USERS` (e.g., a periodic sync script in the `admin-service` that toggles Keycloak realm self-registration off when the limit is reached, or documenting manual admin enforcement if API-based sync is too heavy for MVP)

#### `apps/catalog-service`
- [ ] Add a repository query to calculate the total byte size of all non-trashed files for a specific `owner_id`
- [ ] Expose an internal GET endpoint `/internal/users/{owner_id}/usage` returning current bytes used and the configured max bytes
- [ ] Expose a public GET endpoint `/api/v1/users/me/usage` for the frontend to query the current user's storage utilization

#### `apps/file-service`
- [ ] Before handling an upload stream, make a synchronous call to `/internal/users/{owner_id}/usage` 
- [ ] Calculate if `current_usage + incoming_content_length > quota`. If true, reject the request immediately with a structured quota error
- [ ] Ensure backend error messaging states how much space is left and the size of the rejected file

#### `apps/frontend`
- [ ] Add a `getUserUsage()` request definition in `apps/frontend/src/api/client.ts`
- [ ] Fetch the user storage usage on initial app load and after any successful upload or permanent delete
- [ ] Add a visual progress gauge at the bottom of the left Drive sidebar
- [ ] Format the gauge text in gigabytes (e.g., "400 MB / 1.0 GB used")
- [ ] Enhance the file upload dropzone and queue to surface the new `quota_exceeded` structural error clearly to the user

#### Testing
- [ ] Add `catalog-service` unit tests proving the user usage sum accurately totals non-trashed files
- [ ] Add `file-service` integration test proving an upload is rejected if it pushes the user past their configured limit
- [ ] Update Playwright E2E tests: mock the `/api/v1/users/me/usage` endpoint to return 99% usage, attempt to upload a file, and verify the frontend queue displays a quota error

## 6.15 Security Review and Baseline Hardening

### 6.15.1 Secret and artifact hygiene

- [ ] Add a short `StudyVault/docs/security.md` section explaining the local `--env-file StudyVault/.env` workflow
- [ ] Document that `StudyVault/.env` is required for local Docker Compose but must not be committed or shared
- [ ] Add a pre-commit or CI secret scan using a tool such as `gitleaks` or `trufflehog`
- [ ] Configure the secret scan to fail on real-looking API keys, private keys, database URLs with passwords, Keycloak admin credentials, MinIO credentials, and `STUDYVAULT_INTERNAL_TOKEN`
- [ ] Add an allowlist only for known fake fixtures such as `.env.example` and `.env.test`

### 6.15.2 Frontend exposure and network-call checks

- [ ] Audit all `import.meta.env` usage in `apps/frontend` and confirm only safe `VITE_*` public values are referenced
- [ ] Confirm no backend-only values such as database URLs, internal service tokens, MinIO secrets, or Keycloak admin credentials are referenced by frontend code
- [ ] Build the frontend and search the generated `dist/` output for known secret variable names and local secret values
- [ ] Search frontend source for `apiKey`, `secret`, `password`, `token`, `Authorization`, `Bearer`, and direct service URLs
- [ ] Verify frontend network calls go only through the intended same-origin gateway paths such as `/api/v1/...` and proxied Keycloak paths
- [ ] Confirm the browser never calls internal service hostnames directly, such as `catalog-service`, `file-service`, `search-service`, `activity-service`, `minio`, `postgres`, or `mongo`
- [ ] Confirm no admin service token is sent from the browser
- [ ] Confirm access tokens are sent only in the `Authorization` header for authenticated API calls
- [ ] Confirm no access token, refresh token, temporary password, or reset secret is written to localStorage, sessionStorage, query strings, or application logs
- [ ] Add a Playwright or smoke check that fails if known local secret values appear in page HTML, loaded JavaScript, or captured network request URLs

### 6.15.3 Security headers and browser hardening

- [ ] Add `server_tokens off;` to nginx so version details are not advertised by default
- [ ] Keep `X-Content-Type-Options: nosniff` on browser-facing responses
- [ ] Keep `Referrer-Policy: strict-origin-when-cross-origin` on browser-facing responses
- [ ] Keep `Permissions-Policy` restrictive for unused browser capabilities
- [ ] Add `Cross-Origin-Opener-Policy: same-origin` if it does not break Keycloak login/account flows
- [ ] Add `Cross-Origin-Resource-Policy: same-origin` for same-origin application responses if compatible with proxied assets
- [ ] Prefer CSP `frame-ancestors` over relying only on `X-Frame-Options`
- [ ] Keep `X-Frame-Options: SAMEORIGIN` only as a compatibility fallback while Keycloak silent SSO constraints are evaluated
- [ ] Replace broad `script-src 'unsafe-inline'` with nonce/hash-based exceptions or route-specific CSP where practical
- [ ] Keep `style-src 'unsafe-inline'` only if required by the current frontend/Keycloak rendering path, and document why it remains necessary
- [ ] Add a separate CSP note for `silent-check-sso.html` if that file is the reason inline script is still allowed
- [ ] Add `Cache-Control: no-store` for `/api/v1/admin/` responses and other sensitive JSON responses
- [ ] Add `Cache-Control: no-store` for responses that can include temporary passwords, account-management state, or token-adjacent details
- [ ] Increase production HSTS to a preload-ready value only after end-to-end HTTPS is confirmed stable
- [ ] Add regression tests or nginx config checks for the final browser header set

### 6.15.4 TLS, proxy, and public deployment posture

- [ ] Confirm OAuth redirect URIs, web origins, and public frontend URLs match the real production hostname
- [ ] Confirm cookies and Keycloak session behavior remain correct behind the production proxy

### 6.15.5 Keycloak and authentication hardening

- [ ] Split local/dev Keycloak settings from production Keycloak settings
- [ ] Keep `start-dev` only for local development
- [ ] Use production Keycloak startup mode for deployed environments
- [ ] Enable strict hostname behavior in production
- [ ] Disable direct access grants for the browser SPA client unless a specific tested flow requires them
- [ ] Enable Keycloak brute-force protection for production
- [ ] Keep the public client audience contract aligned with backend JWT audience validation
- [ ] Confirm wrong-audience tokens are rejected by every public service
- [ ] Confirm internal routes cannot be reached with only a browser access token
- [ ] Confirm internal-token values are never exposed to frontend code, frontend build output, or network responses
- [ ] Upgrade Keycloak to a currently supported patched image before production deployment

### 6.15.6 API and admin-route hardening

- [ ] Verify every public `/api/v1/...` route requires the shared auth dependency unless it is intentionally public
- [ ] Verify every admin route requires an admin role check in addition to normal authentication
- [ ] Verify every internal `/internal/...` route requires `X-Internal-Token`
- [ ] Confirm internal routes are not exposed through nginx public routing
- [ ] Add explicit tests for unauthenticated, wrong-role, wrong-audience, and wrong-internal-token access
- [ ] For temporary password return, mark the response `Cache-Control: no-store`
- [ ] For temporary password return, ensure the temporary password is shown only once and is never logged
- [ ] Ensure request and error logs do not include bearer tokens, internal tokens, temporary passwords, reset links, or full database URLs
- [ ] Add log redaction for known sensitive header and field names

### 6.15.7 OWASP baseline review

- [ ] Map current controls and remaining gaps to the OWASP Top 10 categories
- [ ] Document Broken Access Control checks for owner scoping, admin-only routes, and internal-only routes
- [ ] Document Cryptographic Failures checks for TLS mode, HSTS, token handling, and secret storage
- [ ] Document Injection checks for SQLAlchemy query construction, search regex escaping, and input validation
- [ ] Document Insecure Design decisions around temporary passwords, account recovery, and admin operations
- [ ] Document Security Misconfiguration checks for nginx, Keycloak, Compose, CORS, CSP, and trusted hosts
- [ ] Document Vulnerable and Outdated Components checks for frontend packages, Python packages, Docker images, and GitHub Actions
- [ ] Document Identification and Authentication Failure checks for Keycloak client settings, token validation, rate limiting, and brute-force controls
- [ ] Document Software and Data Integrity checks for dependency lockfiles, image pinning, and CI build provenance
- [ ] Document Logging and Monitoring checks for audit usefulness and sensitive-data redaction
- [ ] Document SSRF checks confirming no public user-controlled URL fetch path exists
- [ ] Convert any confirmed OWASP gaps into tracked implementation tasks in this section

### 6.15.8 Dependency, image, and supply-chain hardening

- [ ] Upgrade Vite and frontend dependencies to patched supported versions
- [ ] Run `npm audit` or an equivalent frontend dependency scan in CI
- [ ] Add Python dependency scanning with `pip-audit`, `uv audit`, or an equivalent tool
- [ ] Pin Python dependencies through a lockfile or equivalent reproducible dependency mechanism
- [ ] Scan Docker images for known vulnerabilities before release
- [ ] Pin production Docker images to explicit patch versions or digests where practical
- [ ] Keep local development images flexible only where it materially improves development speed
- [ ] Review GitHub Actions or CI workflows for unpinned third-party actions
- [ ] Pin high-risk CI actions by SHA or trusted version tags
- [ ] Add a release checklist item requiring dependency and image scans to pass

### 6.15.9 Container and Compose hardening

- [ ] Run application containers as non-root users where practical
- [ ] Add `read_only: true` to services that do not need a writable filesystem
- [ ] Add explicit writable temp/cache mounts only where needed
- [ ] Add `cap_drop: ["ALL"]` where service functionality allows it
- [ ] Add `security_opt: ["no-new-privileges:true"]` where compatible
- [ ] Avoid exposing database, Mongo, MinIO, and internal service ports publicly in production
- [ ] Keep only nginx or the intended ingress publicly reachable
- [ ] Keep development-only port mappings clearly marked as local-only
- [ ] Confirm Compose health checks do not require weakening public host validation
- [ ] Confirm backup/export volumes do not include secrets unless encrypted and intentionally retained

### 6.15.10 Logging, monitoring, and sensitive-data handling

- [ ] Define which logs are safe for local troubleshooting and which logs are sensitive
- [ ] Redact `Authorization`, `Cookie`, `Set-Cookie`, `X-Internal-Token`, password, token, secret, and database URL values from logs
- [ ] Ensure ELK or any log dashboard is not publicly exposed without authentication
- [ ] Add basic security event logging for failed auth, denied admin access, internal-token failures, and rate-limit events
- [ ] Ensure security event logs remain useful without recording raw secrets
