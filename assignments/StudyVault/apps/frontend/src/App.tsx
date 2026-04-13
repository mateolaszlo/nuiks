import { FormEvent, startTransition, useEffect, useMemo, useState } from "react";

import { ApiClient } from "./api/client";
import type {
  ActivityRecord,
  AdminAuditEvent,
  AdminErrorRecord,
  AdminHealthSummary,
  AdminPasswordResetResult,
  AdminUserSummary,
  BreadcrumbEntry,
  DriveItem,
} from "./api/types";
import {
  getAccessToken,
  getProfileSummary,
  initializeAuth,
  isAdmin,
  isAuthenticated,
  login,
  logout,
  register,
} from "./auth/keycloak";

type LoadState = "loading" | "ready" | "error";
type DashboardView = "drive" | "trash";
const ROOT_BREADCRUMB: BreadcrumbEntry = { folder_id: null, name: "My Drive" };

function formatDate(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function App() {
  const api = useMemo(() => new ApiClient(getAccessToken), []);
  const [authState, setAuthState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [profileLabel, setProfileLabel] = useState("Anonymous");
  const [adminUser, setAdminUser] = useState(false);
  const [currentView, setCurrentView] = useState<DashboardView>("drive");
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [breadcrumbs, setBreadcrumbs] = useState<BreadcrumbEntry[]>([ROOT_BREADCRUMB]);
  const [currentItems, setCurrentItems] = useState<DriveItem[]>([]);
  const [trashItems, setTrashItems] = useState<DriveItem[]>([]);
  const [searchResults, setSearchResults] = useState<DriveItem[]>([]);
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [adminUsers, setAdminUsers] = useState<AdminUserSummary[]>([]);
  const [adminAudit, setAdminAudit] = useState<AdminAuditEvent[]>([]);
  const [adminErrors, setAdminErrors] = useState<AdminErrorRecord[]>([]);
  const [adminHealth, setAdminHealth] = useState<AdminHealthSummary | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [renameItem, setRenameItem] = useState<DriveItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [moveItem, setMoveItem] = useState<DriveItem | null>(null);
  const [moveTargetFolderId, setMoveTargetFolderId] = useState<string>("");
  const [showCreateFolderForm, setShowCreateFolderForm] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [passwordResetResult, setPasswordResetResult] = useState<AdminPasswordResetResult | null>(null);

  const currentFolderLabel = breadcrumbs[breadcrumbs.length - 1]?.name ?? ROOT_BREADCRUMB.name;
  const canGoUp = breadcrumbs.length > 1;
  const moveDestinations = useMemo(() => {
    const destinations = new Map<string, { value: string; label: string }>();
    destinations.set("", { value: "", label: "My Drive" });
    for (const entry of breadcrumbs) {
      if (entry.folder_id !== null) {
        destinations.set(entry.folder_id, { value: entry.folder_id, label: entry.name });
      }
    }
    for (const item of currentItems) {
      if (item.kind === "folder" && item.item_id !== moveItem?.item_id) {
        destinations.set(item.item_id, { value: item.item_id, label: item.name });
      }
    }
    return Array.from(destinations.values());
  }, [breadcrumbs, currentItems, moveItem]);

  async function loadFolder(folderId: string | null) {
    const catalogPromise = api.listCatalogItems(folderId);
    const breadcrumbsPromise =
      folderId === null
        ? Promise.resolve({ breadcrumbs: [ROOT_BREADCRUMB] })
        : api.getBreadcrumbs(folderId);
    const [catalogPayload, breadcrumbPayload, activityPayload] = await Promise.all([
      catalogPromise,
      breadcrumbsPromise,
      api.listActivity(),
    ]);
    startTransition(() => {
      setCurrentFolderId(folderId);
      setBreadcrumbs(breadcrumbPayload.breadcrumbs);
      setCurrentItems(catalogPayload.items);
      setActivities(activityPayload);
    });
  }

  async function loadTrash() {
    const [trashPayload, activityPayload] = await Promise.all([api.listTrash(), api.listActivity()]);
    startTransition(() => {
      setCurrentView("trash");
      setTrashItems(trashPayload.items);
      setActivities(activityPayload);
    });
  }

  async function refreshAdminPanel() {
    const [usersPayload, auditPayload, healthPayload, errorsPayload] = await Promise.all([
      api.listAdminUsers(),
      api.listAdminAudit(),
      api.getAdminHealth(),
      api.listAdminErrors(),
    ]);
    startTransition(() => {
      setAdminUsers(usersPayload);
      setAdminAudit(auditPayload);
      setAdminHealth(healthPayload);
      setAdminErrors(errorsPayload);
    });
  }

  useEffect(() => {
    async function bootstrap() {
      try {
        const loggedIn = await initializeAuth();
        const authReady = loggedIn || isAuthenticated();
        const adminReady = isAdmin();
        setAuthenticated(authReady);
        setProfileLabel(getProfileSummary());
        setAdminUser(adminReady);
        setAuthState("ready");
        setError(null);
        if (authReady) {
          try {
            if (adminReady) {
              await refreshAdminPanel();
            } else {
              setCurrentView("drive");
              await loadFolder(null);
            }
          } catch (dashboardError) {
            setError(
              dashboardError instanceof Error ? dashboardError.message : String(dashboardError),
            );
          }
        }
      } catch (bootstrapError) {
        setAuthState("error");
        setError(
          bootstrapError instanceof Error ? bootstrapError.message : String(bootstrapError),
        );
      }
    }

    void bootstrap();
  }, []);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults([]);
      setError(null);
      return;
    }

    try {
      setIsBusy(true);
      const payload = await api.search(searchQuery.trim(), { kind: "all" });
      startTransition(() => setSearchResults(payload));
      setError(null);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : "Search failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setError("Choose a file before uploading.");
      return;
    }

    try {
      setIsBusy(true);
      const tags = tagInput
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
      await api.uploadFile(selectedFile, tags, currentFolderId);
      setSelectedFile(null);
      setTagInput("");
      await loadFolder(currentFolderId);
      setError(null);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleTrashItem(item: DriveItem) {
    try {
      setIsBusy(true);
      setRenameItem(null);
      setRenameName("");
      setMoveItem(null);
      setMoveTargetFolderId("");
      if (item.kind === "folder") {
        await api.trashFolder(item.item_id);
      } else {
        await api.trashFile(item.item_id);
      }
      await loadFolder(currentFolderId);
      setError(null);
    } catch (trashError) {
      setError(trashError instanceof Error ? trashError.message : "Move to trash failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = newFolderName.trim();
    if (!trimmedName) {
      setError("Enter a folder name.");
      return;
    }

    try {
      setIsBusy(true);
      await api.createFolder(trimmedName, currentFolderId);
      setNewFolderName("");
      setShowCreateFolderForm(false);
      await loadFolder(currentFolderId);
      setError(null);
    } catch (createFolderError) {
      setError(createFolderError instanceof Error ? createFolderError.message : "Folder creation failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRenameItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameItem) {
      return;
    }
    const trimmedName = renameName.trim();
    if (!trimmedName) {
      setError("Enter a name.");
      return;
    }

    try {
      setIsBusy(true);
      if (renameItem.kind === "folder") {
        await api.renameFolder(renameItem.item_id, trimmedName);
      } else {
        await api.renameFile(renameItem.item_id, trimmedName);
      }
      setRenameItem(null);
      setRenameName("");
      await loadFolder(currentFolderId);
      setError(null);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "Rename failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleMoveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!moveItem) {
      return;
    }

    try {
      setIsBusy(true);
      const targetFolderId = moveTargetFolderId || null;
      if (moveItem.kind === "folder") {
        await api.moveFolder(moveItem.item_id, targetFolderId);
      } else {
        await api.moveFile(moveItem.item_id, targetFolderId);
      }
      setMoveItem(null);
      setMoveTargetFolderId("");
      await loadFolder(currentFolderId);
      setError(null);
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : "Move failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRestoreItem(item: DriveItem) {
    try {
      setIsBusy(true);
      if (item.kind === "folder") {
        await api.restoreFolder(item.item_id);
      } else {
        await api.restoreFile(item.item_id);
      }
      await loadTrash();
      setError(null);
    } catch (restoreError) {
      setError(restoreError instanceof Error ? restoreError.message : "Restore failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDownload(fileId: string, filename: string) {
    try {
      setIsBusy(true);
      const blob = await api.downloadFile(fileId);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setError(null);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Download failed");
    } finally {
      setIsBusy(false);
    }
  }

  function handleStartRename(item: DriveItem) {
    setMoveItem(null);
    setMoveTargetFolderId("");
    setRenameItem(item);
    setRenameName(item.name);
    setError(null);
  }

  function handleCancelRename() {
    setRenameItem(null);
    setRenameName("");
    setError(null);
  }

  function handleStartMove(item: DriveItem) {
    setRenameItem(null);
    setRenameName("");
    setMoveItem(item);
    setMoveTargetFolderId(item.parent_folder_id ?? "");
    setError(null);
  }

  function handleCancelMove() {
    setMoveItem(null);
    setMoveTargetFolderId("");
    setError(null);
  }

  async function handleOpenDrive() {
    try {
      setIsBusy(true);
      setCurrentView("drive");
      await loadFolder(currentFolderId);
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Drive load failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleOpenTrash() {
    try {
      setIsBusy(true);
      setShowCreateFolderForm(false);
      setRenameItem(null);
      setRenameName("");
      setMoveItem(null);
      setMoveTargetFolderId("");
      await loadTrash();
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Trash load failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleOpenFolder(item: DriveItem) {
    if (item.kind !== "folder") {
      return;
    }

    try {
      setIsBusy(true);
      await loadFolder(item.item_id);
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Folder load failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleGoUp() {
    if (!canGoUp) {
      return;
    }
    const nextFolderId = breadcrumbs[breadcrumbs.length - 2]?.folder_id ?? null;

    try {
      setIsBusy(true);
      await loadFolder(nextFolderId);
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Folder load failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleBreadcrumbClick(entry: BreadcrumbEntry) {
    const targetFolderId = entry.folder_id;
    if (targetFolderId === currentFolderId || (targetFolderId === null && currentFolderId === null)) {
      return;
    }

    try {
      setIsBusy(true);
      await loadFolder(targetFolderId);
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Folder load failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAdminAction(action: () => Promise<unknown>) {
    try {
      setIsBusy(true);
      setPasswordResetResult(null);
      await action();
      await refreshAdminPanel();
      setError(null);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Admin action failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function handlePasswordReset(userId: string) {
    try {
      setIsBusy(true);
      const result = await api.resetPassword(userId);
      setPasswordResetResult(result);
      await refreshAdminPanel();
      setError(null);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Password reset failed");
    } finally {
      setIsBusy(false);
    }
  }

  if (authState === "loading") {
    return (
      <main className="shell">
        <section className="hero-card">Loading StudyVault…</section>
      </main>
    );
  }

  if (authState === "error") {
    return (
      <main className="shell">
        <section className="hero-card">
          <h1>StudyVault</h1>
          <p>Authentication setup failed.</p>
          {error ? <p className="error-text">{error}</p> : null}
        </section>
      </main>
    );
  }

  if (!authenticated) {
    return (
      <main className="shell">
        <section className="hero-card">
          <p className="eyebrow">Microservice App</p>
          <h1>StudyVault</h1>
          <p>
            Sign in to upload study materials, review your file catalog, search metadata,
            and inspect recent activity.
          </p>
          <div className="action-row">
            <button className="primary-button" onClick={() => void login()}>
              Log In With Keycloak
            </button>
            <button className="secondary-button" onClick={() => void register()}>
              Create Account
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (adminUser) {
    return (
      <main className="shell">
        <section className="hero-card">
          <div>
            <p className="eyebrow">Admin Console</p>
            <h1>{profileLabel}</h1>
            <p>
              Oversee StudyVault users, audit activity, password resets, and operational
              health from a dedicated admin-only workspace.
            </p>
          </div>
          <div className="action-row">
            <button className="secondary-button" onClick={() => void refreshAdminPanel()} disabled={isBusy}>
              Refresh
            </button>
            <button className="secondary-button" onClick={() => void logout()}>
              Log Out
            </button>
          </div>
        </section>

        <section className="grid admin-summary-grid">
          <article className="panel">
            <h2>Users</h2>
            <div className="summary-number">{adminHealth?.total_users ?? adminUsers.length}</div>
            <p className="muted">
              {adminHealth?.enabled_users ?? 0} enabled, {adminHealth?.admin_users ?? 0} admins
            </p>
          </article>
          <article className="panel">
            <h2>Recent Activity</h2>
            <div className="summary-number">{adminHealth?.recent_uploads ?? 0}</div>
            <p className="muted">
              Uploads. Downloads: {adminHealth?.recent_downloads ?? 0}. Searches:{" "}
              {adminHealth?.recent_searches ?? 0}
            </p>
          </article>
          <article className="panel">
            <h2>Recent Errors</h2>
            <div className="summary-number">{adminHealth?.recent_errors ?? adminErrors.length}</div>
            <p className="muted">Captured from application logs and failure events.</p>
          </article>
        </section>

        <section className="grid admin-main-grid">
          <article className="panel admin-panel-wide">
            <h2>Users</h2>
            {passwordResetResult ? (
              <div className="notice-card">
                Temporary password for <strong>{passwordResetResult.username}</strong>:{" "}
                <code>{passwordResetResult.temporary_password}</code>
              </div>
            ) : null}
            <div className="results">
              {adminUsers.map((user) => (
                <div className="result-card admin-user-card" key={user.user_id}>
                  <div>
                    <strong>{user.username}</strong>
                    <p>{user.email || "No email"}</p>
                    <p>
                      {user.enabled ? "Enabled" : "Disabled"} • Created {formatDate(user.created_at)}
                    </p>
                    <p>{user.roles.join(", ") || "No roles"}</p>
                  </div>
                  <div className="admin-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={isBusy}
                      onClick={() => void handleAdminAction(() => (user.enabled ? api.disableUser(user.user_id) : api.enableUser(user.user_id)))}
                    >
                      {user.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={isBusy}
                      onClick={() =>
                        void handleAdminAction(() =>
                          user.roles.includes("studyvault_admin")
                            ? api.revokeAdmin(user.user_id)
                            : api.grantAdmin(user.user_id),
                        )
                      }
                    >
                      {user.roles.includes("studyvault_admin") ? "Revoke Admin" : "Grant Admin"}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={isBusy}
                      onClick={() => void handlePasswordReset(user.user_id)}
                    >
                      Reset Password
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <h2>System Health</h2>
            <div className="results">
              {(adminHealth?.services ?? []).map((service) => (
                <div className="result-card" key={service.service}>
                  <div>
                    <strong>{service.service}</strong>
                    <p>{service.detail || "No detail"}</p>
                  </div>
                  <span className={service.status === "healthy" ? "status-ok" : "status-bad"}>
                    {service.status}
                  </span>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="grid admin-main-grid">
          <article className="panel">
            <h2>Audit Events</h2>
            <div className="results">
              {adminAudit.map((event) => (
                <div className="result-card" key={event.event_id}>
                  <div>
                    <strong>{event.event_type}</strong>
                    <p>{event.message}</p>
                    <p>
                      {event.actor_username || event.target_username || "Unknown user"}
                      {event.filename ? ` • ${event.filename}` : ""}
                    </p>
                  </div>
                  <span>{formatDate(event.created_at)}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <h2>Errors / Low-Level Info</h2>
            <div className="results">
              {adminErrors.length === 0 ? <p className="muted">No recent errors detected.</p> : null}
              {adminErrors.map((record) => (
                <div className="result-card" key={record.event_id}>
                  <div>
                    <strong>{record.service}</strong>
                    <p>{record.message}</p>
                    <p>
                      {record.event_name || "application_error"}
                      {record.request_id ? ` • ${record.request_id}` : ""}
                    </p>
                  </div>
                  <span>{formatDate(record.created_at)}</span>
                </div>
              ))}
            </div>
          </article>
        </section>

        {error ? <p className="error-text">{error}</p> : null}
      </main>
    );
  }

  return (
    <main className="shell">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Signed in</p>
          <h1>{profileLabel}</h1>
          <p>Browse your drive, upload into the current folder, search files, and review recent activity.</p>
        </div>
        <div className="action-row">
          <button
            className={currentView === "drive" ? "primary-button" : "secondary-button"}
            type="button"
            onClick={() => void handleOpenDrive()}
            disabled={isBusy}
          >
            My Drive
          </button>
          <button
            className={currentView === "trash" ? "primary-button" : "secondary-button"}
            type="button"
            onClick={() => void handleOpenTrash()}
            disabled={isBusy}
          >
            Trash
          </button>
          <button className="secondary-button" onClick={() => void logout()}>
            Log Out
          </button>
        </div>
      </section>

      <section className="grid">
        <article className="panel">
          <h2>Upload</h2>
          <form className="stack" onSubmit={handleUpload}>
            <p className="muted">Destination: {currentFolderLabel}</p>
            <label className="stack">
              <span>File</span>
              <input
                id="upload-file"
                type="file"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <label className="stack">
              <span>Tags</span>
              <input
                id="upload-tags"
                type="text"
                placeholder="math, notes, finals"
                value={tagInput}
                onChange={(event) => setTagInput(event.target.value)}
              />
            </label>
            <button className="primary-button" type="submit" disabled={isBusy}>
              {isBusy ? "Uploading…" : "Upload File"}
            </button>
          </form>
        </article>

        <article className="panel">
          <h2>Search</h2>
          <form className="stack" onSubmit={handleSearch}>
            <input
              type="search"
              placeholder="Search files and folders"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
            <button className="secondary-button" type="submit" disabled={isBusy}>
              Search
            </button>
          </form>
          <div className="results">
            {!searchQuery.trim() ? <p className="muted">Search files and folders by name, type, or tag.</p> : null}
            {searchQuery.trim() && searchResults.length === 0 ? (
              <p className="muted">No matching files or folders yet.</p>
            ) : null}
            {searchResults.map((item) => (
              <div className="result-card drive-item-card" key={item.item_id}>
                <div>
                  <div className="drive-item-title-row">
                    <span className={`item-kind-badge item-kind-${item.kind}`}>{item.kind}</span>
                    <strong>{item.name}</strong>
                  </div>
                  {item.kind === "folder" ? (
                    <p>Folder • Open to browse contents</p>
                  ) : (
                    <>
                      <p>
                        {item.mime_type || "Unknown type"} • {item.size ?? 0} bytes
                      </p>
                      <p>{item.tags.join(", ") || "No tags"}</p>
                    </>
                  )}
                </div>
                <div className="drive-item-actions">
                  {item.kind === "folder" ? (
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => void handleOpenFolder(item)}
                      disabled={isBusy}
                    >
                      Open
                    </button>
                  ) : (
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => void handleDownload(item.item_id, item.name)}
                      disabled={isBusy}
                    >
                      Download
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid drive-grid">
        <article className="panel drive-panel">
          {currentView === "drive" ? (
            <>
              <div className="drive-header">
                <div>
                  <h2>My Drive</h2>
                  <p className="muted">
                    {currentFolderLabel} • {currentItems.length} item{currentItems.length === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="action-row">
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => {
                      setShowCreateFolderForm((value) => !value);
                      setError(null);
                    }}
                    disabled={isBusy}
                  >
                    {showCreateFolderForm ? "Close" : "New Folder"}
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void handleGoUp()}
                    disabled={!canGoUp || isBusy}
                  >
                    Up
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void loadFolder(currentFolderId)}
                    disabled={isBusy}
                  >
                    Refresh
                  </button>
                </div>
              </div>
              {showCreateFolderForm ? (
                <form className="stack create-folder-form" onSubmit={handleCreateFolder}>
                  <label className="stack">
                    <span>Folder name</span>
                    <input
                      type="text"
                      placeholder="Lecture Notes"
                      value={newFolderName}
                      onChange={(event) => setNewFolderName(event.target.value)}
                      disabled={isBusy}
                    />
                  </label>
                  <p className="muted">Location: {currentFolderLabel}</p>
                  <div className="action-row">
                    <button className="primary-button" type="submit" disabled={isBusy}>
                      {isBusy ? "Creating…" : "Create Folder"}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => {
                        setShowCreateFolderForm(false);
                        setNewFolderName("");
                        setError(null);
                      }}
                      disabled={isBusy}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              ) : null}
              <div className="breadcrumbs" aria-label="Breadcrumbs">
                {breadcrumbs.map((entry, index) => {
                  const isLast = index === breadcrumbs.length - 1;
                  return (
                    <div className="breadcrumb-segment" key={`${entry.folder_id ?? "root"}-${index}`}>
                      {index > 0 ? <span className="breadcrumb-separator">/</span> : null}
                      {isLast ? (
                        <span className="breadcrumb-current">{entry.name}</span>
                      ) : (
                        <button
                          className="breadcrumb-button"
                          type="button"
                          onClick={() => void handleBreadcrumbClick(entry)}
                          disabled={isBusy}
                        >
                          {entry.name}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="results">
                {currentItems.length === 0 ? (
                  <p className="muted">
                    {currentFolderId ? "This folder is empty." : "Create content by uploading a file into My Drive."}
                  </p>
                ) : null}
                {currentItems.map((item) => (
                  <div className="result-card drive-item-card" key={item.item_id}>
                    <div>
                      <div className="drive-item-title-row">
                        <span className={`item-kind-badge item-kind-${item.kind}`}>{item.kind}</span>
                        <strong>{item.name}</strong>
                      </div>
                      {item.kind === "folder" ? (
                        <p>Folder • Open to view contents</p>
                      ) : (
                        <>
                          <p>
                            {item.mime_type || "Unknown type"} • {item.size ?? 0} bytes
                          </p>
                          <p>{item.tags.join(", ") || "No tags"}</p>
                        </>
                      )}
                      {renameItem?.item_id === item.item_id ? (
                        <form className="stack rename-item-form" onSubmit={handleRenameItem}>
                          <label className="stack">
                            <span>Rename {item.kind}</span>
                            <input
                              type="text"
                              value={renameName}
                              onChange={(event) => setRenameName(event.target.value)}
                              disabled={isBusy}
                            />
                          </label>
                          <div className="action-row">
                            <button className="primary-button" type="submit" disabled={isBusy}>
                              {isBusy ? "Saving…" : "Save"}
                            </button>
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={handleCancelRename}
                              disabled={isBusy}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : null}
                      {moveItem?.item_id === item.item_id ? (
                        <form className="stack move-item-form" onSubmit={handleMoveItem}>
                          <label className="stack">
                            <span>Move {item.kind} to</span>
                            <select
                              value={moveTargetFolderId}
                              onChange={(event) => setMoveTargetFolderId(event.target.value)}
                              disabled={isBusy}
                            >
                              {moveDestinations.map((destination) => (
                                <option key={destination.value || "root"} value={destination.value}>
                                  {destination.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <div className="action-row">
                            <button className="primary-button" type="submit" disabled={isBusy}>
                              {isBusy ? "Moving…" : "Move"}
                            </button>
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={handleCancelMove}
                              disabled={isBusy}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : null}
                    </div>
                    <div className="drive-item-actions">
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleStartRename(item)}
                        disabled={isBusy}
                      >
                        Rename
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => handleStartMove(item)}
                        disabled={isBusy}
                      >
                        Move
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => void handleTrashItem(item)}
                        disabled={isBusy}
                      >
                        Trash
                      </button>
                      {item.kind === "folder" ? (
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => void handleOpenFolder(item)}
                          disabled={isBusy}
                        >
                          Open
                        </button>
                      ) : (
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => void handleDownload(item.item_id, item.name)}
                          disabled={isBusy}
                        >
                          Download
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="drive-header">
                <div>
                  <h2>Trash</h2>
                  <p className="muted">
                    {trashItems.length} item{trashItems.length === 1 ? "" : "s"} awaiting purge or restore
                  </p>
                </div>
                <div className="action-row">
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void loadTrash()}
                    disabled={isBusy}
                  >
                    Refresh
                  </button>
                </div>
              </div>
              <div className="results">
                {trashItems.length === 0 ? (
                  <p className="muted">Trash is empty.</p>
                ) : null}
                {trashItems.map((item) => (
                  <div className="result-card drive-item-card trash-item-card" key={item.item_id}>
                    <div>
                      <div className="drive-item-title-row">
                        <span className={`item-kind-badge item-kind-${item.kind}`}>{item.kind}</span>
                        <strong>{item.name}</strong>
                      </div>
                      <p>Deleted {formatDate(item.trashed_at)}</p>
                      <p>Purge scheduled for {formatDate(item.purge_after)}</p>
                      {item.kind === "file" ? (
                        <>
                          <p>
                            {item.mime_type || "Unknown type"} • {item.size ?? 0} bytes
                          </p>
                          <p>{item.tags.join(", ") || "No tags"}</p>
                        </>
                      ) : (
                        <p>Folder • Restore to recover contents metadata.</p>
                      )}
                    </div>
                    <div className="drive-item-actions">
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => void handleRestoreItem(item)}
                        disabled={isBusy}
                      >
                        Restore
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </article>

        <article className="panel">
          <h2>Recent Activity</h2>
          <div className="results">
            {activities.length === 0 ? <p className="muted">Activity will appear after the first upload.</p> : null}
            {activities.map((activity) => (
              <div className="result-card" key={activity.activity_id}>
                <div>
                  <strong>{activity.action}</strong>
                  <p>{activity.filename || "Unnamed item"}</p>
                </div>
                <span>{formatDate(activity.created_at)}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      {error ? <p className="error-text">{error}</p> : null}
    </main>
  );
}
