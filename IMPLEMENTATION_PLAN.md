# IMPLEMENTATION_PLAN.md

# StudyVault: Google Drive Lite Implementation Plan

## Document status

- **Target repo:** `mateolaszlo/nuiks` → `assignments/StudyVault`
- **Goal:** evolve the current StudyVault MVP from a flat personal file vault into a single-user, Google Drive–style file manager
- **Included in scope:** folders, nested navigation, rename, move, trash, restore, 30-day retention purge
- **Explicitly out of scope:** file sharing, ACLs, public links, collaboration, version history, preview/editing
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

Today, the system is file-centric and effectively flat. The main missing capabilities are:

- first-class folders
- hierarchical parent-child relationships
- folder-aware listing/navigation
- rename/move semantics
- soft deletion with trash lifecycle
- restore semantics
- hard purge after retention expiry

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

---

## 3. Current architecture summary

### 3.1 Frontend

The frontend is a React app that currently behaves like a dashboard:

- upload files
- search files
- list "My Files"
- view recent activity
- download files

This needs to evolve into a folder browser UI.

### 3.2 file-service

Currently responsible for:

- receiving file upload
- storing bytes in MinIO
- orchestrating downstream metadata writes
- serving downloads

This service should continue to own file-byte lifecycle and file mutation orchestration.

### 3.3 catalog-service

Currently the canonical metadata store in PostgreSQL.

This service should become the source of truth for:

- folders
- file/folder parent relationships
- trash state
- retention timestamps
- folder navigation data

### 3.4 search-service

Currently stores searchable file metadata in MongoDB.

This service should become a denormalized search index for both:

- files
- folders

### 3.5 activity-service

Currently upload-centric.

This service should evolve into a generic event stream for file/folder operations.

### 3.6 MinIO object store

Should continue to store only file bytes. Folder operations should be metadata-only.

---

## 4. Core design decisions

## 4.1 Treat folders as first-class metadata objects

Do **not** fake folders by encoding paths into filenames.

Reason:

- filenames already reject path separators
- path-like filenames would be fragile and difficult to validate
- trash/restore/move behavior would become messy
- folder search/navigation would be much harder

### Decision

Create a dedicated folder metadata model and store folder hierarchy in PostgreSQL.

## 4.2 Keep object keys stable

Do **not** rewrite MinIO object keys on file rename or file move.

### Why

Current object keys are already independent from filename and folder placement. That is good.

### Decision

A file’s MinIO object key remains immutable for the life of the file.

- rename = metadata update only
- move = metadata update only
- trash = metadata update only
- restore = metadata update only
- permanent delete = delete metadata + delete MinIO object

## 4.3 Make catalog-service the hierarchy source of truth

All folder structure and trash state should live in PostgreSQL through catalog-service.

Search and activity remain derived views.

## 4.4 Use soft delete for trash

Deleting from normal views should not immediately remove data.

### Decision

Trashing an item sets:

- `trashed_at`
- `purge_after = trashed_at + 30 days`
- original location metadata used for restore

Hard deletion only happens in the purge worker.

## 4.5 Use root as `NULL parent_folder_id`

Do not create a special synthetic root folder row unless there is a strong operational reason.

### Decision

- root-level items have `parent_folder_id = NULL`
- breadcrumbs start from a virtual root label in the frontend

This keeps the data model simpler.

## 4.6 Favor simple schema changes over production-style migration layers

Because the app is pre-release and local/test data is disposable, do not over-engineer schema rollout.

### Decision

- keep database changes explicit and versioned
- but it is acceptable for development/test to reset the database when a phase changes the schema
- do not build dual-write or dual-read compatibility layers unless they directly unblock the current phase
- prefer one clean schema per phase over preserving every intermediate local database state forever

---

## 5. Proposed data model

## 5.1 Recommended approach

Use **separate tables** for `folders` and `files`.

This is the best balance for the current codebase because:

- files already exist and are modeled directly today
- file upload/download logic is file-specific
- a unified `items` table would be cleaner long-term, but requires broader refactoring now

---

## 5.2 PostgreSQL schema

### 5.2.1 `folders` table

```sql
CREATE TABLE folders (
    folder_id UUID PRIMARY KEY,
    owner_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL,
    parent_folder_id UUID NULL REFERENCES folders(folder_id) ON DELETE RESTRICT,
    path_depth INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trashed_at TIMESTAMPTZ NULL,
    purge_after TIMESTAMPTZ NULL,
    original_parent_folder_id UUID NULL,
    deleted_by_cascade BOOLEAN NOT NULL DEFAULT FALSE
);
```

### 5.2.2 `files` table changes

Assuming the existing `files` table already stores canonical file metadata, add:

```sql
ALTER TABLE files
    ADD COLUMN parent_folder_id UUID NULL REFERENCES folders(folder_id) ON DELETE RESTRICT,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN trashed_at TIMESTAMPTZ NULL,
    ADD COLUMN purge_after TIMESTAMPTZ NULL,
    ADD COLUMN original_parent_folder_id UUID NULL;
```

### 5.2.3 Uniqueness constraints

Folders must be unique among active siblings, and files should also avoid same-name conflicts if that is the desired UX.

Recommended active-sibling uniqueness:

```sql
CREATE UNIQUE INDEX uq_folders_active_sibling_name
ON folders(owner_id, COALESCE(parent_folder_id, '00000000-0000-0000-0000-000000000000'::uuid), normalized_name)
WHERE trashed_at IS NULL;
```

```sql
CREATE UNIQUE INDEX uq_files_active_sibling_name
ON files(owner_id, COALESCE(parent_folder_id, '00000000-0000-0000-0000-000000000000'::uuid), LOWER(filename))
WHERE trashed_at IS NULL;
```

If you want to allow duplicate filenames in a folder, skip the second index. For a Drive-like UX, enforcing uniqueness usually reduces UI ambiguity.

### 5.2.4 Performance indexes

```sql
CREATE INDEX idx_folders_owner_parent_active
ON folders(owner_id, parent_folder_id)
WHERE trashed_at IS NULL;

CREATE INDEX idx_files_owner_parent_active
ON files(owner_id, parent_folder_id)
WHERE trashed_at IS NULL;

CREATE INDEX idx_folders_owner_purge_after
ON folders(owner_id, purge_after)
WHERE trashed_at IS NOT NULL;

CREATE INDEX idx_files_owner_purge_after
ON files(owner_id, purge_after)
WHERE trashed_at IS NOT NULL;

CREATE INDEX idx_folders_owner_trashed_at
ON folders(owner_id, trashed_at);

CREATE INDEX idx_files_owner_trashed_at
ON files(owner_id, trashed_at);
```

### 5.2.5 Development note on schema changes

The SQL above is the target schema shape. During pre-release development, it is acceptable to reach this state with whichever mechanism best fits the repo today:

- migration files
- init SQL updates
- ORM schema scripts
- a reset-and-recreate workflow in Docker/dev

The key requirement is **repeatability**, not preserving local throwaway data across every phase.

---

## 5.3 Shared backend models

Add shared models in `packages/backend-common`.

### 5.3.1 `FolderRecord`

```python
class FolderRecord(BaseModel):
    folder_id: UUID
    owner_id: str
    name: str
    normalized_name: str
    parent_folder_id: UUID | None = None
    path_depth: int
    created_at: datetime
    updated_at: datetime
    trashed_at: datetime | None = None
    purge_after: datetime | None = None
    original_parent_folder_id: UUID | None = None
    deleted_by_cascade: bool = False
```

### 5.3.2 `DriveItem`

This is the model the frontend should consume for folder listings and search results.

```python
class DriveItem(BaseModel):
    item_id: UUID
    kind: Literal["file", "folder"]
    owner_id: str
    name: str
    parent_folder_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    trashed_at: datetime | None = None
    purge_after: datetime | None = None

    # file-only fields
    mime_type: str | None = None
    size: int | None = None
    tags: list[str] = []
    object_key: str | None = None
```

### 5.3.3 Request DTOs

Add shared request types:

- `CreateFolderRequest`
- `RenameItemRequest`
- `MoveItemRequest`
- `TrashItemRequest`
- `RestoreItemRequest`
- `ListFolderItemsResponse`
- `BreadcrumbNode`
- `TrashListResponse`

### 5.3.4 Generic activity event

```python
class ItemActivityEvent(BaseModel):
    activity_id: UUID
    owner_id: str
    action: Literal[
        "file_uploaded",
        "folder_created",
        "item_renamed",
        "item_moved",
        "item_trashed",
        "item_restored",
        "item_hard_deleted",
    ]
    item_id: UUID
    item_kind: Literal["file", "folder"]
    item_name: str
    parent_folder_id: UUID | None = None
    target_parent_folder_id: UUID | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## 6. Naming and validation rules

## 6.1 Folder names

Folder names should follow nearly the same rules as filenames today.

### Rules

- trimmed name must not be empty
- max length 255
- reject control characters
- reject `/` and `\`
- reject reserved dot-only values if desired (`.` and `..`)
- comparison for uniqueness should be case-insensitive using `normalized_name`

## 6.2 File rename rules

Reuse existing filename validation where possible.

## 6.3 Move rules

### File move

Allowed when:

- file belongs to current user
- source file is not trashed
- target folder exists
- target folder belongs to current user
- target folder is not trashed
- no active name conflict at target

### Folder move

Allowed when:

- folder belongs to current user
- folder is not trashed
- target folder belongs to current user or is root
- target folder is not the folder itself
- target folder is not a descendant of the folder
- no active sibling folder name conflict at target

## 6.4 Delete rules

### File delete

Moves file to trash.

### Folder delete

Moves folder and all descendants to trash.

## 6.5 Restore rules

Restore should prefer the original parent location.

If the original parent no longer exists or is still trashed:

- restore to root
- return a response flag so the UI can show: "Restored to root because original folder no longer exists"

If a same-name conflict exists on restore:

Recommended policy:

- return `409 Conflict`
- let UI ask user to rename before restore or restore with a suffix

For MVP, a server-side suffix policy is acceptable, but `409` is easier to reason about and keeps behavior explicit.

---

## 7. API design

## 7.1 Public API overview

### Folder/navigation endpoints (catalog-service)

- `GET /api/catalog/items`
- `GET /api/catalog/folders/{folder_id}`
- `GET /api/catalog/breadcrumbs/{folder_id}`
- `POST /api/catalog/folders`
- `PATCH /api/catalog/folders/{folder_id}`
- `DELETE /api/catalog/folders/{folder_id}`
- `POST /api/catalog/folders/{folder_id}/restore`
- `GET /api/catalog/trash`

### File endpoints (file-service)

- `POST /api/files`
- `GET /api/files/{file_id}`
- `PATCH /api/files/{file_id}`
- `DELETE /api/files/{file_id}`
- `POST /api/files/{file_id}/restore`

### Search endpoint (search-service)

- `GET /api/search`

### Activity endpoint (activity-service)

- `GET /api/activity/me`

---

## 7.2 Exact endpoint specs

## 7.2.1 List current folder items

### `GET /api/catalog/items?parent_id=<uuid|null>&include_trashed=false`

Returns folders and files under a folder.

#### Query params

- `parent_id`: optional UUID, omit or pass null/root semantics for root listing
- `include_trashed`: default `false`
- `sort`: optional (`name_asc`, `name_desc`, `created_desc`, `updated_desc`)

#### Response

```json
{
  "parent_folder_id": null,
  "items": [
    {
      "item_id": "3d4a...",
      "kind": "folder",
      "owner_id": "user-123",
      "name": "Projects",
      "parent_folder_id": null,
      "created_at": "2026-04-08T10:00:00Z",
      "updated_at": "2026-04-08T10:00:00Z",
      "trashed_at": null,
      "purge_after": null,
      "mime_type": null,
      "size": null,
      "tags": [],
      "object_key": null
    },
    {
      "item_id": "5a22...",
      "kind": "file",
      "owner_id": "user-123",
      "name": "notes.pdf",
      "parent_folder_id": null,
      "created_at": "2026-04-08T10:05:00Z",
      "updated_at": "2026-04-08T10:05:00Z",
      "trashed_at": null,
      "purge_after": null,
      "mime_type": "application/pdf",
      "size": 12345,
      "tags": ["study"],
      "object_key": "user-123/5a22..."
    }
  ]
}
```

---

## 7.2.2 Create folder

### `POST /api/catalog/folders`

#### Request

```json
{
  "name": "Projects",
  "parent_folder_id": null
}
```

#### Success response

`201 Created`

```json
{
  "folder_id": "3d4a...",
  "owner_id": "user-123",
  "name": "Projects",
  "normalized_name": "projects",
  "parent_folder_id": null,
  "path_depth": 0,
  "created_at": "2026-04-08T10:00:00Z",
  "updated_at": "2026-04-08T10:00:00Z",
  "trashed_at": null,
  "purge_after": null,
  "original_parent_folder_id": null,
  "deleted_by_cascade": false
}
```

#### Failure cases

- `400` invalid name
- `404` parent folder not found
- `409` sibling folder with same name already exists

---

## 7.2.3 Rename folder

### `PATCH /api/catalog/folders/{folder_id}`

#### Request

```json
{
  "name": "Personal Projects"
}
```

#### Optional future extension

Allow move in same endpoint, but for clarity, this plan recommends **separate rename and move operations** internally.

#### Failure cases

- `400` invalid name
- `404` folder not found
- `409` name conflict in target parent

---

## 7.2.4 Move folder

### Recommended endpoint

### `POST /api/catalog/folders/{folder_id}/move`

#### Request

```json
{
  "target_parent_folder_id": "b7f4..."
}
```

#### Failure cases

- `404` folder or target not found
- `409` folder cannot be moved into itself or descendant
- `409` name conflict in target folder

---

## 7.2.5 Trash folder

### `DELETE /api/catalog/folders/{folder_id}`

Soft delete only.

#### Response

`204 No Content`

#### Behavior

- folder gets `trashed_at`
- folder gets `purge_after`
- descendants are also marked trashed
- descendants should record cascade deletion metadata

---

## 7.2.6 Restore folder

### `POST /api/catalog/folders/{folder_id}/restore`

#### Response

```json
{
  "folder_id": "3d4a...",
  "restored_to_parent_folder_id": null,
  "restored_to_root": true,
  "message": "Original parent was unavailable, item restored to root"
}
```

---

## 7.2.7 Breadcrumbs

### `GET /api/catalog/breadcrumbs/{folder_id}`

#### Response

```json
{
  "breadcrumbs": [
    { "folder_id": null, "name": "My Drive" },
    { "folder_id": "1111...", "name": "Projects" },
    { "folder_id": "2222...", "name": "2026" }
  ]
}
```

---

## 7.2.8 Trash view

### `GET /api/catalog/trash`

#### Response

```json
{
  "items": [
    {
      "item_id": "3d4a...",
      "kind": "folder",
      "name": "Old Stuff",
      "trashed_at": "2026-03-10T12:00:00Z",
      "purge_after": "2026-04-09T12:00:00Z"
    },
    {
      "item_id": "5a22...",
      "kind": "file",
      "name": "draft.docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "size": 42111,
      "trashed_at": "2026-03-11T12:00:00Z",
      "purge_after": "2026-04-10T12:00:00Z"
    }
  ]
}
```

---

## 7.2.9 Upload file into a folder

### `POST /api/files`

Use multipart form-data.

#### Fields

- `file`: binary
- `tags`: optional repeated field or JSON-encoded list
- `parent_folder_id`: optional UUID

#### Behavior

- store bytes in MinIO
- create canonical file metadata in catalog-service
- index in search-service
- write activity event

#### Failure cases

- `404` parent folder not found
- `409` name conflict in target folder
- `422` invalid folder state (e.g. trashed)

---

## 7.2.10 Rename file

### `PATCH /api/files/{file_id}`

#### Request

```json
{
  "name": "final-notes.pdf"
}
```

---

## 7.2.11 Move file

### `POST /api/files/{file_id}/move`

#### Request

```json
{
  "target_parent_folder_id": "b7f4..."
}
```

#### Why separate route

It keeps rename and move semantics simpler and easier to test.

---

## 7.2.12 Trash file

### `DELETE /api/files/{file_id}`

Soft delete only.

---

## 7.2.13 Restore file

### `POST /api/files/{file_id}/restore`

#### Response

```json
{
  "file_id": "5a22...",
  "restored_to_parent_folder_id": null,
  "restored_to_root": true,
  "message": "Original parent was unavailable, file restored to root"
}
```

---

## 7.2.14 Search

### `GET /api/search?q=<text>&include_trashed=false&kind=all&parent_id=<uuid|null>`

#### Recommended semantics

- by default search only active items
- support kind filter: `file`, `folder`, `all`
- optionally scope search to a folder if needed later

#### Response

```json
{
  "items": [
    {
      "item_id": "3d4a...",
      "kind": "folder",
      "name": "Projects",
      "parent_folder_id": null,
      "trashed_at": null
    },
    {
      "item_id": "5a22...",
      "kind": "file",
      "name": "project-plan.pdf",
      "mime_type": "application/pdf",
      "size": 12345,
      "parent_folder_id": "3d4a...",
      "trashed_at": null
    }
  ]
}
```

---

## 7.3 Internal API design

These routes are service-to-service only.

## 7.3.1 catalog-service internal routes

- `POST /internal/catalog/files`
- `GET /internal/catalog/files/{file_id}`
- `PATCH /internal/catalog/files/{file_id}`
- `DELETE /internal/catalog/files/{file_id}`
- `POST /internal/catalog/files/{file_id}/restore`
- `DELETE /internal/catalog/files/{file_id}/hard-delete`

- `POST /internal/catalog/folders`
- `GET /internal/catalog/folders/{folder_id}`
- `PATCH /internal/catalog/folders/{folder_id}`
- `POST /internal/catalog/folders/{folder_id}/move`
- `DELETE /internal/catalog/folders/{folder_id}`
- `POST /internal/catalog/folders/{folder_id}/restore`
- `DELETE /internal/catalog/folders/{folder_id}/hard-delete`

- `GET /internal/catalog/trash/expired?before=<timestamp>&limit=<n>`

## 7.3.2 search-service internal routes

Recommended routes:

- `PUT /internal/search/items/{item_id}`
  - upsert file or folder index document
- `DELETE /internal/search/items/{item_id}`

## 7.3.3 activity-service internal routes

- `POST /internal/activity/events`

Accepts generic `ItemActivityEvent`.

---

## 8. Service implementation plan

## 8.1 `packages/backend-common`

### Changes

1. Add new models:
   - `FolderRecord`
   - `DriveItem`
   - folder request/response DTOs
   - generic activity event
2. Keep `FileRecord` temporarily for compatibility if it materially simplifies incremental refactors
3. Add reusable validation helpers:
   - `validate_folder_name`
   - `normalize_name`
   - conflict helpers

### Deliverables

- shared Python models compile cleanly
- no service breaks while migrating incrementally

---

## 8.2 catalog-service

### Responsibilities after refactor

- source of truth for file metadata
- source of truth for folder metadata
- source of truth for hierarchy and trash state

### Implementation tasks

#### Repositories / data access

Add repository methods for:

- `create_folder(owner_id, name, parent_folder_id)`
- `get_folder(folder_id, owner_id)`
- `list_items(owner_id, parent_folder_id, include_trashed=False)`
- `rename_folder(folder_id, owner_id, new_name)`
- `move_folder(folder_id, owner_id, target_parent_folder_id)`
- `trash_folder(folder_id, owner_id)`
- `restore_folder(folder_id, owner_id)`
- `get_breadcrumbs(folder_id, owner_id)`
- `list_trash(owner_id)`
- `get_expired_trash(before, limit)`
- `hard_delete_file(file_id)`
- `hard_delete_folder(folder_id)`
- `move_file(file_id, owner_id, target_parent_folder_id)`
- `rename_file(file_id, owner_id, new_name)`
- `trash_file(file_id, owner_id)`
- `restore_file(file_id, owner_id)`

#### Validation logic

Add logic to prevent:

- move folder into itself
- move folder into descendant
- use trashed folder as destination
- rename/move into sibling name conflict

#### Cascading trash algorithm

When folder is trashed:

1. mark folder trashed
2. recursively mark descendants trashed
3. set descendant `deleted_by_cascade = true`
4. preserve original parent info on root deleted folder and optionally descendants if you want precise restoration semantics

#### Restore algorithm

When folder is restored:

1. attempt restore to original parent
2. if original parent unavailable, restore top-level folder to root
3. restore descendants relative to restored tree
4. clear `trashed_at`, `purge_after`, `deleted_by_cascade`

### Recommended implementation note

For initial implementation, recursive SQL CTEs or iterative repository traversal are both acceptable. If using SQLAlchemy with recursive CTEs becomes cumbersome, iterative traversal is easier to reason about for MVP.

### Schema-change note

For this repo state, it is acceptable if catalog-service schema work is introduced with a clean reset of the local/test PostgreSQL container. The important outcome is that the schema is reproducible and tests can bootstrap it reliably.

---

## 8.3 file-service

### Responsibilities after refactor

- upload bytes
- download bytes
- coordinate file lifecycle mutations across catalog/search/activity
- physically delete objects during purge

### Changes

#### Upload

Extend upload handler to accept `parent_folder_id`.

#### Rename file

Add endpoint that:

1. validates user ownership
2. calls catalog-service to rename metadata
3. reindexes search doc
4. writes activity event

#### Move file

Add endpoint that:

1. validates user ownership
2. calls catalog-service to move metadata
3. reindexes search doc
4. writes activity event

#### Trash file

Add endpoint that:

1. calls catalog-service soft-delete
2. reindexes or removes active visibility in search
3. writes activity event

#### Restore file

Add endpoint that:

1. restores metadata through catalog-service
2. reindexes search doc
3. writes activity event

#### Hard delete file

Used by purge worker:

1. fetch canonical file metadata including object key
2. delete search document
3. delete MinIO object
4. hard-delete canonical metadata
5. write activity event if desired

### Object store interface changes

Add:

```python
class ObjectStoreProtocol(Protocol):
    def store(self, object_key: str, stream: BinaryIO, content_type: str | None = None) -> None: ...
    def get(self, object_key: str) -> BinaryIO: ...
    def delete(self, object_key: str) -> None: ...
    def ping(self) -> bool: ...
```

---

## 8.4 search-service

### Goal

Index both files and folders using a single search document shape.

### Proposed Mongo document

```json
{
  "item_id": "uuid",
  "kind": "file",
  "owner_id": "user-123",
  "name": "project-plan.pdf",
  "parent_folder_id": "uuid-or-null",
  "mime_type": "application/pdf",
  "size": 12345,
  "tags": ["project"],
  "trashed_at": null,
  "created_at": "2026-04-08T10:05:00Z",
  "updated_at": "2026-04-08T10:05:00Z"
}
```

### Implementation tasks

- update index model
- support folder indexing
- default search to `trashed_at == null`
- optionally support `include_trashed=true`
- allow `kind` filter
- add upsert endpoint by `item_id`
- add delete endpoint by `item_id`

### Reindex support

Add a simple command or admin task to rebuild the search index from catalog metadata.

This is useful during rollout and for operational recovery.

### Development note

Because Mongo data is disposable in local/test environments, it is acceptable to rebuild or reseed the search index instead of supporting complex index migrations.

---

## 8.5 activity-service

### Goal

Support generic user-facing activity entries.

### Implementation tasks

- replace upload-only event contract with `ItemActivityEvent`
- update storage schema as needed
- update rendering logic to support friendly messages for:
  - uploaded file
  - created folder
  - renamed item
  - moved item
  - trashed item
  - restored item
  - permanently deleted item

### Suggested message mapping

- `file_uploaded` → `Uploaded {item_name}`
- `folder_created` → `Created folder {item_name}`
- `item_renamed` → `Renamed {old_name} to {new_name}`
- `item_moved` → `Moved {item_name}`
- `item_trashed` → `Moved {item_name} to trash`
- `item_restored` → `Restored {item_name}`
- `item_hard_deleted` → `Permanently deleted {item_name}`

### Development note

Because activity data is also non-production at this stage, it is acceptable to change the stored event shape directly and recreate local data when needed.

---

## 8.6 Frontend

## 8.6.1 UX goals

Replace the current flat file dashboard with a folder browser.

### Main navigation

- My Drive
- Trash
- Search
- Activity

### Main content areas

#### My Drive view

- action bar
  - upload
  - new folder
- breadcrumbs
- file/folder list
- row actions
  - rename
  - move
  - delete
  - download (files only)

#### Trash view

- trashed items list
- date deleted
- purge date / days remaining
- restore
- delete forever (optional user action, even if worker also exists)

#### Search view

- search input
- item type indicator
- parent path display
- click result to navigate to containing folder or open item

## 8.6.2 State model

Add frontend state for:

- `currentFolderId`
- `currentItems`
- `breadcrumbs`
- `selectedItem`
- `trashItems`
- `searchQuery`
- modal state for create / rename / move
- loading and error states per action

## 8.6.3 Component recommendations

Suggested new components:

- `DriveLayout`
- `DriveToolbar`
- `Breadcrumbs`
- `DriveItemTable`
- `DriveItemRow`
- `CreateFolderModal`
- `RenameItemModal`
- `MoveItemModal`
- `TrashView`
- `SearchResults`

## 8.6.4 User behavior rules

- double click or row click on folder navigates into folder
- file click can remain neutral or select row; download stays explicit
- trashed items do not appear in normal folder listings
- if restore falls back to root, show a visible toast/message
- if rename/move conflicts, show explicit error from server

---

## 9. Trash lifecycle design

## 9.1 Soft delete semantics

When a user deletes a file:

- set `trashed_at = now()`
- set `purge_after = now() + interval '30 days'`
- copy current `parent_folder_id` to `original_parent_folder_id`
- remove from normal folder views
- exclude from default search results
- show in trash

When a user deletes a folder:

- apply same metadata to the folder
- recursively mark descendants trashed
- descendants inherit effective trash visibility through explicit metadata marking

## 9.2 Restore semantics

### File restore

1. if original parent exists and is active, restore there
2. else restore to root
3. if conflict at restore destination, return `409`

### Folder restore

1. restore top-level folder to original parent if possible, else root
2. restore descendants under the restored folder tree
3. if conflict at destination, return `409`

## 9.3 Hard delete semantics

The purge worker will permanently delete items where:

- `trashed_at IS NOT NULL`
- `purge_after <= now()`

For files:

- delete MinIO object
- delete search doc
- delete canonical metadata

For folders:

- delete search doc
- delete canonical metadata
- no object store action needed

---

## 10. Purge worker design

## 10.1 Recommendation

Create a dedicated lightweight worker, for example:

- `purge-worker` container, or
- scheduled command within `file-service`

A dedicated worker is cleaner operationally.

## 10.2 Schedule

Daily is sufficient for MVP.

For tests/dev, make interval configurable.

## 10.3 Algorithm

1. ask catalog-service for expired trash items in batches
2. process files first or process by type with safe ordering
3. for each expired file:
   - remove from search
   - delete MinIO object
   - hard-delete metadata
4. for each expired folder:
   - ensure descendant leaves are already handled or hard-delete recursively in safe order
5. log success/failure
6. continue batch processing until empty

## 10.4 Failure handling

If MinIO delete fails:

- do **not** remove canonical metadata yet
- log structured failure
- retry on next run

If search delete fails:

- log error
- continue only if canonical state is still authoritative and reindex tools exist
- ideally retry

### Recommended consistency policy

For purge, object-delete success should be required before canonical file metadata is removed.

---

## 11. Schema evolution plan

This section intentionally avoids production-style rollout requirements because the project is still pre-release.

## 11.1 Schema change order

Target order:

1. add new columns to `files`
2. create `folders`
3. add indexes and constraints
4. backfill existing files if needed:
   - `parent_folder_id = NULL`
   - `updated_at = created_at`
   - `trashed_at = NULL`
   - `purge_after = NULL`
   - `original_parent_folder_id = NULL`

## 11.2 Acceptable implementation methods

Any of the following are acceptable if they keep the repo reproducible:

- migration files
- updated init SQL
- ORM-managed schema updates
- reset-and-recreate database workflow during development/testing

## 11.3 Practical rule for this repo

If a phase changes the canonical schema substantially, it is acceptable to:

1. update schema definitions
2. recreate the local/test PostgreSQL container or database
3. reseed baseline data if required
4. rerun tests

The important thing is that the next developer session or Codex run can reliably reproduce the expected schema.

## 11.4 Application phase order

### Phase 1

- add shared models and schema changes
- keep current APIs working where practical

### Phase 2

- add catalog folder APIs
- add file upload with `parent_folder_id`
- add search/activity generic models

### Phase 3

- add frontend folder browser
- add rename/move/trash/restore

### Phase 4

- add purge worker
- add reindex/admin scripts
- remove obsolete compatibility code

## 11.5 Backward compatibility stance

Because the app is not live yet:

- existing local/test data does **not** need to be preserved across major schema changes
- compatibility code should be temporary and minimal
- old containers/databases can be reset rather than migrated in place if that is simpler

The only compatibility behavior worth preserving is the **logical** behavior that older files, once reloaded into the new schema, appear at root by default.

---

## 12. Error handling and consistency model

## 12.1 Recommended consistency approach

The current system already performs synchronous downstream fan-out during upload.

Continue that pattern for new operations, but be explicit about failure handling.

### Rename / move / trash / restore file

Suggested sequence:

1. update canonical metadata first
2. upsert/delete search doc
3. append activity event
4. return success with warnings only if non-critical downstream failed

### Folder operations

Suggested sequence:

1. update canonical folder metadata first
2. upsert affected folder search docs
3. append activity event
4. for descendant items, either:
   - bulk reindex if required, or
   - rely on search query semantics and targeted updates depending on index design

## 12.2 What is authoritative?

Catalog-service / PostgreSQL is authoritative.

Search-service and activity-service are derived systems.

### Rule

If search or activity is temporarily inconsistent, catalog data wins.

This should also be reflected in operational tooling.

---

## 13. Testing plan

## 13.1 Unit tests

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

## 13.2 API/integration tests

- create folder → upload file into folder → list folder contents
- nested folder navigation
- file move between folders
- folder move between folders
- folder trash cascade updates descendants
- restore after original parent removal falls back to root
- purge worker deletes expired items

## 13.3 Frontend E2E tests

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

## 13.4 Docker/test environment rule

If a test run requires `docker compose` or local service startup:

- start only what is needed
- run the relevant tests
- always shut services down after tests finish, whether they pass or fail

This should be treated as mandatory cleanup, especially for Codex-driven iterative development.

---

## 14. Suggested implementation phases and time estimate

## 14.1 Phase breakdown

### Phase 1: shared models + schema foundation

- backend-common models
- schema changes
- repository scaffolding

### Phase 2: catalog folder APIs

- folder CRUD
- hierarchy listing
- breadcrumbs
- trash metadata

### Phase 3: file mutation APIs

- upload-to-folder
- rename/move/trash/restore file
- object-store delete support

### Phase 4: search/activity refactor

- generic search docs
- generic activity events

### Phase 5: frontend drive UX

- new layout
- folder browser
- trash view
- modals/actions

### Phase 6: purge worker + polish

- worker
- logs
- retries
- E2E fixes

## 14.2 Delivery estimate

### Fast MVP

Approximately **2–4 weeks** for one strong full-stack engineer.

### Realistic pre-release iteration

Approximately **3–6 weeks** for one engineer working phase-by-phase with tests and cleanup, depending on frontend depth and edge-case polish.

This estimate assumes:
- no sharing scope
- disposable dev/test data
- no zero-downtime rollout work
- one-phase-at-a-time implementation with reliable test feedback

---

## 15. Edge cases and policy decisions

These should be explicitly agreed before implementation to avoid churn.

### 15.1 Name conflicts on restore

**Recommendation:** return `409 Conflict` and let the user resolve it.

### 15.2 Restore when original parent is unavailable

**Recommendation:** restore to root and inform the UI.

### 15.3 Folder delete behavior

**Recommendation:** cascade soft-delete descendants immediately.

### 15.4 Empty folders

Allowed.

### 15.5 Search behavior

**Recommendation:** normal search excludes trashed items by default.

### 15.6 Downloading trashed files

**Recommendation:** disallow normal download of trashed items unless explicitly restored first.

### 15.7 Hard delete from UI

Optional.

For MVP, it is acceptable to show only restore in the trash UI and rely on automatic purge. Adding “Delete forever” is a nice enhancement but not required.

---

## 16. Repo-level task list

## 16.1 `packages/backend-common`

- [x] Add `FolderRecord`
- [x] Add `DriveItem`
- [x] Add folder DTOs
- [x] Add generic activity DTOs
- [x] Add name validation helpers
- [x] Extend `FileRecord` with folder/trash metadata

## 16.2 `apps/catalog-service`

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

## 16.3 `apps/file-service`

- [x] Extend upload request to accept `parent_folder_id`
- [x] Add rename file endpoint
- [x] Add move file endpoint
- [x] Add trash file endpoint
- [x] Add restore file endpoint
- [x] Add hard delete method for purge worker
- [x] Add `delete()` to object store abstraction

## 16.4 `apps/search-service`

- [ ] Replace file-only index doc with item index doc
- [ ] Add folder indexing
- [x] Add delete by `item_id`
- [ ] Add filters for trashed and kind
- [ ] Add reindex script

## 16.5 `apps/activity-service`

- [ ] Replace upload-only activity model
- [ ] Accept generic item events
- [ ] Update activity message mapping

## 16.6 `apps/frontend`

- [ ] Replace flat file list with folder browser
- [ ] Add breadcrumbs
- [ ] Add create folder UI
- [ ] Add rename/move UI
- [ ] Add trash page
- [ ] Update search results to support folders

## 16.7 New worker or command

- [ ] Add purge worker
- [ ] Add batch processing
- [ ] Add retries/logging
- [ ] Make schedule configurable

---

## 17. Definition of done

This feature is complete when all of the following are true:

- users can create nested folders
- users can upload files into a selected folder
- users can rename files and folders
- users can move files and folders
- users can delete files and folders to trash
- users can restore files and folders from trash
- trashed items are hidden from normal folder listings
- trashed items are hidden from normal search
- trash shows retention expiry information
- expired trashed files are permanently deleted from MinIO and metadata
- activity feed includes folder and file operations
- automated tests cover happy paths and core edge cases

---

## 18. Recommended next step after this plan

Implement in this order:

1. **shared models + validation**
2. **catalog schema changes**
3. **catalog folder APIs**
4. **file upload-to-folder + rename/move/trash/restore**
5. **search/activity generalization**
6. **frontend folder browser**
7. **purge worker**

This order keeps the plan aligned with a pre-release, one-phase-at-a-time workflow and avoids doing production-style rollout work before the core Drive behavior exists.
