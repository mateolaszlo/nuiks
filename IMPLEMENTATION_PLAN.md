# IMPLEMENTATION_PLAN.md

# StudyVault: Google Drive Clone Implementation Plan

## Document status

- **Target repo:** `mateolaszlo/nuiks` → `assignments/StudyVault`
- **Goal:** evolve the current StudyVault from a flat personal file vault into a single-user, Google Drive–style file manager
- **Included in scope:** folders, nested navigation, rename, move, trash, restore, 30-day retention purge
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



## 3. Error handling and consistency model

## 3.1 What is authoritative?

Catalog-service / PostgreSQL is authoritative.

Search-service and activity-service are derived systems.

### Rule

If search or activity is temporarily inconsistent, catalog data wins.

This should also be reflected in operational tooling.

---

## 4. Testing plan

## 4.1 Unit tests

### Shared validation

- valid folder names
- invalid folder names
- normalization rules
- restore destination resolution

### Catalog-service

- create folder at root
- create nested folder
- reject duplicate sibling name
- move folder to root
- reject move into self
- reject move into descendant
- trash folder cascade
- restore folder to original parent
- restore folder to root fallback
- conflict on restore with same-name sibling

### File-service

- upload into folder
- rename file
- move file
- trash file
- restore file
- hard delete file deletes object store entry

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
- nested folder navigation
- file move between folders
- folder move between folders
- folder trash cascade updates descendants
- restore after original parent removal falls back to root
- purge worker deletes expired items

## 4.3 Frontend E2E tests

Using Playwright:

- create folder from root
- navigate with breadcrumbs
- upload file into current folder
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

## 6.3 `apps/file-service`

- [x] Extend upload request to accept `parent_folder_id`
- [x] Add rename file endpoint
- [x] Add move file endpoint
- [x] Add trash file endpoint
- [x] Add restore file endpoint
- [x] Add hard delete method for purge worker
- [x] Add `delete()` to object store abstraction

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
- [ ] Replace the main `My Drive` list view with a Google Drive-style responsive grid
- [ ] Show only file/folder name and kind in grid tiles
- [x] Add single-selection state for current Drive items
- [x] Open selected item details in the right-side panel
- [ ] Change folder navigation from single click to double click
- [x] Add topbar `Activity` button and move activity feed into the right-side panel
- [x] Hide the right-side panel when no item is selected and activity is closed
- [x] Add `Info` action to the file/folder context menu
- [ ] Keep drag-and-drop move working with folder tiles
- [ ] Keep `Search` and `Trash` as list views in this phase
- [x] Keep folder navigation usable during the transition away from single-click open

### 6.6.1 Drive browser UX refresh

The current Drive browser shows a vertical list with inline metadata and opens folders on single click. This phase changes the main `My Drive` view to behave more like Google Drive.

#### Goals

- make the main browser visually scan like a grid of items instead of a table
- reduce clutter by moving metadata out of the main surface
- support selection-first interaction with a contextual info panel
- keep existing backend APIs and file/folder operations intact

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

## 6.7 New worker or command

- [x] Add purge worker command
- [x] Process expired files
- [x] Process expired folders
- [x] Add batch processing
- [x] Add retries/logging
- [x] Make schedule configurable
