# StudyVault Security Review

Date: 2026-04-03

## Methodology

Manual review of the current StudyVault code and deployment config under `assignments/StudyVault`, focused on:

- auth and internal trust boundaries
- user input handling for filenames, tags, search text, IDs, and admin query params
- file upload/download behavior
- frontend rendering of user-controlled fields
- secret/default configuration posture

This report is code-and-config based. It distinguishes confirmed issues from lower-confidence follow-up items.

## Executive Summary

StudyVault has a reasonable basic structure for this project: JWT verification is pinned to `RS256`, internal `/internal/*` routes are no longer exposed through the public gateway, and the frontend renders user-controlled text through normal React JSX rather than raw HTML.

The main confirmed risks are input-handling and operational-hardening gaps:

1. file uploads are read fully into memory with no size limit
2. user search text is passed directly into Mongo `$regex` with no escaping or length bound
3. download filenames are reflected directly into `Content-Disposition`
4. several sensitive secrets and seeded credentials still ship with weak defaults
5. temporary admin password resets are returned directly to the frontend UI
6. several request parameters are effectively unbounded, which increases abuse and denial-of-service risk

None of the reviewed findings look like a trivial unauthenticated internet-to-RCE path. The highest practical risks are denial-of-service, credential/default-secret abuse, and avoidable exposure of sensitive operational or account data.

## Findings

### High

#### 1. Unbounded file upload is read fully into memory

- Severity: High
- Affected paths:
  - `apps/file-service/app/services/files.py`
  - `apps/file-service/app/api/routes.py`
- Why it is a problem:
  - `FileService.upload_file()` calls `await upload.read()` and stores the entire request body in memory before any size check.
  - There is no route-level size enforcement, no configured maximum upload size, and no streaming/chunked write path.
- Realistic impact:
  - An authenticated user can submit a very large file and force high memory usage in `file-service`.
  - This can degrade or crash the service and is a straightforward denial-of-service vector.
- Recommended fix:
  - enforce a maximum upload size before fully reading the body
  - reject oversized files with `413 Payload Too Large`
  - prefer streaming to object storage instead of buffering the whole file in RAM
  - add tests for empty, normal, and oversized uploads

#### 2. Raw search input is used directly in Mongo `$regex`

- Severity: High
- Affected paths:
  - `apps/search-service/app/repositories/search.py`
  - `apps/search-service/app/services/search.py`
  - `apps/search-service/app/api/routes.py`
- Why it is a problem:
  - `MongoSearchRepository.search()` builds `{"$regex": query, "$options": "i"}` directly from user input.
  - Search text is not escaped and is not length-limited.
  - This allows regex metacharacters and expensive patterns instead of a literal search string.
- Realistic impact:
  - Authenticated users can trigger pathological regex evaluation or broad scans.
  - This increases the risk of regex-based denial of service and inconsistent search semantics.
- Recommended fix:
  - treat user search as a literal string by escaping regex metacharacters
  - enforce a reasonable max length on `q`
  - consider indexed search primitives or pre-normalized fields instead of ad hoc regex on multiple fields
  - add tests for metacharacters like `.*`, nested quantifiers, and very long search strings

### Medium

#### 3. Download response reflects raw filename into `Content-Disposition`

- Severity: Medium
- Affected paths:
  - `apps/file-service/app/api/routes.py`
  - `packages/backend-common/studyvault_backend_common/models.py`
- Why it is a problem:
  - Download responses build `content-disposition` as `attachment; filename="{file_record.filename}"`.
  - `file_record.filename` originates from the uploaded client filename and is not normalized or encoded for header safety.
- Realistic impact:
  - Crafted filenames containing quotes, separators, or control characters can produce malformed response headers.
  - Depending on server/client behavior, this can cause header confusion or odd download-name handling.
- Recommended fix:
  - sanitize or normalize filenames before persistence
  - use a safe `Content-Disposition` builder that supports RFC 5987 / `filename*`
  - strip CR/LF and other unsafe header characters
  - add tests for quotes, semicolons, path separators, unicode, and control characters

#### 4. Filenames and tags are accepted with effectively no validation

- Severity: Medium
- Affected paths:
  - `apps/file-service/app/api/routes.py`
  - `apps/file-service/app/services/files.py`
  - `packages/backend-common/studyvault_backend_common/models.py`
- Why it is a problem:
  - Upload filenames, MIME type, and tags are accepted as provided by the client.
  - Shared schema modules currently only re-export `FileRecord`; there are no dedicated constrained request models for uploads.
  - `FileRecord.create()` also embeds the raw filename into the storage object key.
- Realistic impact:
  - Unbounded tag counts and lengths can create oversized records, noisy logs, and inconsistent search behavior.
  - Raw filenames with slashes or unusual characters create unpredictable object keys and downstream display behavior.
- Recommended fix:
  - add explicit request validation for:
    - filename length and allowed characters
    - tag count
    - tag length
    - MIME type length and format
  - normalize filenames before storing and before building object keys
  - reject clearly malformed or abusive inputs up front

#### 5. Temporary password resets are returned to the browser UI

- Severity: Medium
- Affected paths:
  - `apps/activity-service/app/services/admin_integrations.py`
  - `apps/activity-service/app/services/admin.py`
  - `apps/frontend/src/App.tsx`
  - `apps/frontend/src/api/types.ts`
- Why it is a problem:
  - `KeycloakAdminClient.reset_password()` generates a temporary password and returns it to the API caller.
  - The frontend displays the returned password directly in the admin console.
- Realistic impact:
  - Anyone with admin UI access, browser history access, screenshots, screen sharing, or frontend telemetry could capture temporary credentials.
  - This increases secret exposure compared with out-of-band delivery or forced user-managed reset flows.
- Recommended fix:
  - prefer a reset flow that does not return credentials to the browser
  - if temporary passwords must exist, expose them through a narrower operational path with strong audit expectations
  - consider triggering required-action resets in Keycloak instead of displaying a generated password

#### 6. Weak default secrets remain in active config

- Severity: Medium
- Affected paths:
  - `.env.example`
  - `infra/docker/compose/docker-compose.yml`
  - `infra/keycloak/studyvault-realm.template.json`
  - `apps/*/app/core/config.py`
- Why it is a problem:
  - The stack still ships operator-facing defaults such as:
    - `KC_BOOTSTRAP_ADMIN_PASSWORD=admin`
    - `STUDYVAULT_INTERNAL_TOKEN=studyvault-internal-token-change-me`
    - `FILE_S3_ACCESS_KEY=minioadmin`
    - `FILE_S3_SECRET_KEY=minioadmin`
    - `MINIO_ROOT_PASSWORD=minioadmin`
    - `POSTGRES_PASSWORD=studyvault`
    - seeded user passwords `demo123` and `admin123`
  - Internal token defaults are also baked into service config fallbacks.
- Realistic impact:
  - Public or semi-public deployments that are not fully reconfigured remain easy to guess or reuse.
  - A misconfigured deployment can inherit known credentials across auth, storage, and service-to-service trust.
- Recommended fix:
  - remove weak active defaults where feasible and fail closed for required secrets
  - keep `.env.example` as documentation, but use clearly non-working placeholders for sensitive values
  - document credential rotation expectations for public deployments
  - consider removing seeded production-like user passwords from normal deployment flow

#### 7. Admin and search limit/query parameters are not bounded

- Severity: Medium
- Affected paths:
  - `apps/activity-service/app/api/routes.py`
  - `apps/activity-service/app/services/admin.py`
  - `apps/search-service/app/api/routes.py`
- Why it is a problem:
  - `limit` on admin audit and error endpoints is accepted as a plain `int` with no min/max.
  - search query `q` is accepted as a plain `str` with no max length.
- Realistic impact:
  - Large `limit` values can amplify upstream load against Keycloak and Elasticsearch.
  - Very large search strings increase log volume and query-processing cost.
- Recommended fix:
  - constrain admin `limit` parameters with explicit upper bounds
  - constrain search query length and reject empty-or-too-long inputs consistently
  - add tests for negative, zero, and oversized values

### Low

#### 8. User-controlled search text is logged verbatim

- Severity: Low
- Affected paths:
  - `apps/search-service/app/services/search.py`
  - observability stack consuming application logs
- Why it is a problem:
  - Search queries are logged as `query=normalized_query`.
  - Queries may contain personal data, copied secrets, or intentionally noisy payloads.
- Realistic impact:
  - Sensitive user-entered text may be retained in Elasticsearch/Kibana longer than intended.
  - Logging large or abusive queries also increases observability noise.
- Recommended fix:
  - consider truncating logged queries or logging only metadata such as length and result count
  - define whether search text is considered sensitive user data for retention purposes

#### 9. Client-provided MIME type is trusted for storage and download

- Severity: Low
- Affected paths:
  - `apps/file-service/app/services/files.py`
  - `apps/file-service/app/repositories/object_store.py`
  - `apps/file-service/app/api/routes.py`
- Why it is a problem:
  - Upload MIME type comes from `UploadFile.content_type` and is persisted directly.
  - That value is later used as the response `media_type` and S3 `ContentType`.
- Realistic impact:
  - Files can be mislabeled, causing confusing or unsafe browser behavior depending on future proxying or inline rendering decisions.
  - Current download flow uses attachment disposition, which reduces the risk but does not eliminate data-integrity concerns.
- Recommended fix:
  - validate or derive MIME type server-side where practical
  - maintain an allowlist if only a small set of file types is intended
  - keep attachment behavior for downloads unless inline rendering is explicitly required

#### 10. `auth_disabled` remains a high-impact switch across services

- Severity: Low
- Affected paths:
  - `packages/backend-common/studyvault_backend_common/auth.py`
  - `apps/*/app/core/config.py`
  - `infra/docker/compose/docker-compose.yml`
- Why it is a problem:
  - When `auth_disabled` is enabled, services accept a fixed synthetic user and bypass real JWT validation.
  - This is useful for tests, but dangerous if enabled in the wrong environment.
- Realistic impact:
  - A deployment mistake can silently disable authentication across API surfaces.
- Recommended fix:
  - keep it off by default, which is already true
  - document it as test-only
  - consider refusing to start with `auth_disabled=true` outside explicit test/dev contexts

## Positive Notes / Already Hardened

- Shared JWT verification is pinned to `RS256` in `packages/backend-common/studyvault_backend_common/auth.py` instead of trusting the token header for algorithm choice.
- Public nginx routing no longer exposes `/internal/catalog/*`, `/internal/search/*`, or `/internal/activity/*`.
- The frontend does not use `dangerouslySetInnerHTML`; filenames, emails, tags, audit messages, and error text are rendered through normal React JSX text escaping.
- Frontend search requests use `encodeURIComponent(query)` before constructing the URL.
- Keycloak DB credentials are now env-driven rather than hard-coded in the Postgres init script.

## Follow-Up Review Targets

- Verify whether FastAPI / Starlette or the deployment proxy already enforces any request-body size cap in front of `UploadFile.read()`. The application code itself does not.
- Review whether object-store bucket policies, MinIO exposure, and browser download behavior introduce any additional file-serving risks beyond the current attachment response.
- Review Elasticsearch/Kibana retention and access policy for audit data, emails, and logged search queries.
- Consider a second pass focused on dependency hygiene and supply-chain review for Python and Node packages, since this review was primarily code/config behavior focused.
