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
type MoveDestination = { value: string; label: string };

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

function formatBytes(value: number | null | undefined): string {
  if (!value) {
    return "0 B";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function AuthScreen(props: {
  title: string;
  subtitle: string;
  error?: string | null;
  loading?: boolean;
}) {
  const { title, subtitle, error, loading } = props;

  return (
    <main className="auth-shell">
      <section className="auth-stage">
        <div className="auth-brand-row">
          <div className="brand-mark" aria-hidden="true">
            <span className="brand-mark-blue" />
            <span className="brand-mark-green" />
            <span className="brand-mark-yellow" />
          </div>
          <div>
            <p className="eyebrow">StudyVault</p>
            <h1>{title}</h1>
          </div>
        </div>
        <p className="auth-copy">{subtitle}</p>
        {loading ? <p className="muted">Preparing authentication…</p> : null}
        {!loading ? (
          <div className="action-row">
            <button className="primary-button" onClick={() => void login()}>
              Log In With Keycloak
            </button>
            <button className="secondary-button" onClick={() => void register()}>
              Create Account
            </button>
          </div>
        ) : null}
        {error ? <p className="error-text">{error}</p> : null}
      </section>
    </main>
  );
}

function ItemKindBadge({ kind }: { kind: DriveItem["kind"] }) {
  return <span className={`item-kind-badge item-kind-${kind}`}>{kind}</span>;
}

function NavButton(props: {
  active?: boolean;
  icon: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  const { active = false, icon, label, onClick, disabled = false } = props;
  return (
    <button
      className={active ? "nav-button nav-button-active" : "nav-button"}
      type="button"
      onClick={onClick}
      disabled={disabled}
    >
      <span className="nav-icon" aria-hidden="true">
        {icon}
      </span>
      <span>{label}</span>
    </button>
  );
}

function AppTopBar(props: {
  profileLabel: string;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSearch: (event: FormEvent<HTMLFormElement>) => void;
  onLogout: () => void;
  isBusy: boolean;
  title: string;
}) {
  const { profileLabel, searchQuery, onSearchQueryChange, onSearch, onLogout, isBusy, title } = props;

  return (
    <header className="topbar">
      <div className="topbar-title">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <span className="brand-mark-blue" />
            <span className="brand-mark-green" />
            <span className="brand-mark-yellow" />
          </div>
          <div>
            <p className="eyebrow">StudyVault</p>
            <strong>{title}</strong>
          </div>
        </div>
      </div>
      <form className="topbar-search" onSubmit={onSearch}>
        <label className="sr-only" htmlFor="global-search">
          Search files and folders
        </label>
        <input
          id="global-search"
          type="search"
          placeholder="Search files and folders"
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
        />
        <button className="secondary-button" type="submit" disabled={isBusy}>
          Search
        </button>
      </form>
      <div className="topbar-actions">
        <div className="profile-chip">
          <span className="profile-avatar" aria-hidden="true">
            {profileLabel.slice(0, 1).toUpperCase()}
          </span>
          <span>{profileLabel}</span>
        </div>
        <button className="secondary-button" type="button" onClick={onLogout}>
          Log Out
        </button>
      </div>
    </header>
  );
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
  const driveCountLabel =
    currentView === "drive"
      ? `${currentItems.length} item${currentItems.length === 1 ? "" : "s"}`
      : `${trashItems.length} item${trashItems.length === 1 ? "" : "s"}`;

  const moveDestinations = useMemo<MoveDestination[]>(() => {
    const destinations = new Map<string, MoveDestination>();
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
      folderId === null ? Promise.resolve({ breadcrumbs: [ROOT_BREADCRUMB] }) : api.getBreadcrumbs(folderId);
    const [catalogPayload, breadcrumbPayload, activityPayload] = await Promise.all([
      catalogPromise,
      breadcrumbsPromise,
      api.listActivity(),
    ]);
    startTransition(() => {
      setCurrentFolderId(folderId);
      setCurrentView("drive");
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
              await loadFolder(null);
            }
          } catch (dashboardError) {
            setError(dashboardError instanceof Error ? dashboardError.message : String(dashboardError));
          }
        }
      } catch (bootstrapError) {
        setAuthState("error");
        setError(bootstrapError instanceof Error ? bootstrapError.message : String(bootstrapError));
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

  function renderSearchResults() {
    if (!searchQuery.trim() && searchResults.length === 0) {
      return (
        <section className="surface content-surface">
          <div className="section-header">
            <div>
              <p className="eyebrow">Search</p>
              <h2>Search</h2>
            </div>
          </div>
          <p className="muted">Search files and folders by name, type, or tag.</p>
        </section>
      );
    }

    return (
      <section className="surface content-surface">
        <div className="section-header">
          <div>
            <p className="eyebrow">Search</p>
            <h2>Search Results</h2>
          </div>
          <span className="section-meta">
            {searchResults.length} match{searchResults.length === 1 ? "" : "es"}
          </span>
        </div>
        <div className="table-list">
          {searchResults.length === 0 ? (
            <div className="empty-state">
              <strong>No matching files or folders yet.</strong>
              <p>Try a broader name or tag.</p>
            </div>
          ) : null}
          {searchResults.map((item) => (
            <div className="table-row table-row-search" key={item.item_id}>
              <div className="table-main">
                <div className="table-title-row">
                  <ItemKindBadge kind={item.kind} />
                  <strong>{item.name}</strong>
                </div>
                {item.kind === "folder" ? (
                  <p className="muted">Folder available in My Drive.</p>
                ) : (
                  <p className="muted">
                    {item.mime_type || "Unknown type"} • {formatBytes(item.size)} •{" "}
                    {item.tags.join(", ") || "No tags"}
                  </p>
                )}
              </div>
              <div className="table-actions">
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
      </section>
    );
  }

  function renderDriveRows(items: DriveItem[]) {
    return items.map((item) => (
      <div className="table-row" key={item.item_id}>
        <div className="table-main">
          <div className="table-title-row">
            <ItemKindBadge kind={item.kind} />
            <strong>{item.name}</strong>
          </div>
          {item.kind === "folder" ? (
            <p className="muted">Folder • Open to browse contents.</p>
          ) : (
            <p className="muted">
              {item.mime_type || "Unknown type"} • {formatBytes(item.size)} •{" "}
              {item.tags.join(", ") || "No tags"}
            </p>
          )}
          {renameItem?.item_id === item.item_id ? (
            <form className="inline-editor" onSubmit={handleRenameItem}>
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
                <button className="secondary-button" type="button" onClick={handleCancelRename} disabled={isBusy}>
                  Cancel
                </button>
              </div>
            </form>
          ) : null}
          {moveItem?.item_id === item.item_id ? (
            <form className="inline-editor" onSubmit={handleMoveItem}>
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
                <button className="secondary-button" type="button" onClick={handleCancelMove} disabled={isBusy}>
                  Cancel
                </button>
              </div>
            </form>
          ) : null}
        </div>
        <div className="table-actions">
          <button className="secondary-button" type="button" onClick={() => handleStartRename(item)} disabled={isBusy}>
            Rename
          </button>
          <button className="secondary-button" type="button" onClick={() => handleStartMove(item)} disabled={isBusy}>
            Move
          </button>
          <button className="secondary-button" type="button" onClick={() => void handleTrashItem(item)} disabled={isBusy}>
            Trash
          </button>
          {item.kind === "folder" ? (
            <button className="secondary-button" type="button" onClick={() => void handleOpenFolder(item)} disabled={isBusy}>
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
    ));
  }

  function renderDriveWorkspace() {
    return (
      <div className="app-shell">
        <aside className="sidebar">
          <div className="sidebar-section">
            <button
              className="primary-button sidebar-primary"
              type="button"
              onClick={() => {
                setShowCreateFolderForm((value) => !value);
                setError(null);
              }}
              disabled={isBusy}
            >
              {showCreateFolderForm ? "Close" : "New"}
            </button>
          </div>
          <nav className="sidebar-nav" aria-label="Primary">
            <NavButton active={currentView === "drive"} icon="▣" label="My Drive" onClick={() => void handleOpenDrive()} disabled={isBusy} />
            <NavButton active={currentView === "trash"} icon="⌦" label="Trash" onClick={() => void handleOpenTrash()} disabled={isBusy} />
          </nav>
          <section className="sidebar-section side-card">
            <p className="eyebrow">Current Location</p>
            <strong>{currentFolderLabel}</strong>
            <p className="muted">{driveCountLabel}</p>
          </section>
          <section className="sidebar-section side-card">
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
          </section>
        </aside>

        <section className="workspace">
          <AppTopBar
            profileLabel={profileLabel}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            onSearch={handleSearch}
            onLogout={() => void logout()}
            isBusy={isBusy}
            title="Drive"
          />

          {error ? <div className="error-banner">{error}</div> : null}

          <div className="workspace-body">
            <div className="content-column">
              {renderSearchResults()}

              <section className="surface content-surface">
                <div className="section-header section-header-drive">
                  <div>
                    <p className="eyebrow">{currentView === "drive" ? "My Drive" : "Trash"}</p>
                    <h2>{currentView === "drive" ? currentFolderLabel : "Trash"}</h2>
                  </div>
                  <div className="action-row">
                    {currentView === "drive" ? (
                      <>
                        <button className="secondary-button" type="button" onClick={() => void handleGoUp()} disabled={!canGoUp || isBusy}>
                          Up
                        </button>
                        <button className="secondary-button" type="button" onClick={() => void loadFolder(currentFolderId)} disabled={isBusy}>
                          Refresh
                        </button>
                      </>
                    ) : (
                      <button className="secondary-button" type="button" onClick={() => void loadTrash()} disabled={isBusy}>
                        Refresh
                      </button>
                    )}
                  </div>
                </div>

                {currentView === "drive" ? (
                  <>
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
                    {showCreateFolderForm ? (
                      <form className="inline-editor create-folder-panel" onSubmit={handleCreateFolder}>
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
                    <div className="table-list">
                      {currentItems.length === 0 ? (
                        <div className="empty-state">
                          <strong>{currentFolderId ? "This folder is empty." : "Your drive is empty."}</strong>
                          <p>{currentFolderId ? "Upload or create a folder here." : "Upload a file or create a folder to get started."}</p>
                        </div>
                      ) : null}
                      {renderDriveRows(currentItems)}
                    </div>
                  </>
                ) : (
                  <div className="table-list">
                    {trashItems.length === 0 ? (
                      <div className="empty-state">
                        <strong>Trash is empty.</strong>
                        <p>Items sent to trash will stay here until restored or purged.</p>
                      </div>
                    ) : null}
                    {trashItems.map((item) => (
                      <div className="table-row table-row-trash" key={item.item_id}>
                        <div className="table-main">
                          <div className="table-title-row">
                            <ItemKindBadge kind={item.kind} />
                            <strong>{item.name}</strong>
                          </div>
                          <p className="muted">Deleted {formatDate(item.trashed_at)} • Purge scheduled for {formatDate(item.purge_after)}</p>
                          {item.kind === "file" ? (
                            <p className="muted">
                              {item.mime_type || "Unknown type"} • {formatBytes(item.size)} •{" "}
                              {item.tags.join(", ") || "No tags"}
                            </p>
                          ) : (
                            <p className="muted">Folder • Restore to recover contents metadata.</p>
                          )}
                        </div>
                        <div className="table-actions">
                          <button className="primary-button" type="button" onClick={() => void handleRestoreItem(item)} disabled={isBusy}>
                            Restore
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>

            <aside className="activity-column">
              <section className="surface side-card">
                <div className="section-header">
                  <div>
                    <p className="eyebrow">Recent Activity</p>
                    <h2>Recent Activity</h2>
                  </div>
                </div>
                <div className="table-list activity-list">
                  {activities.length === 0 ? (
                    <div className="empty-state empty-state-compact">
                      <strong>No activity yet.</strong>
                      <p>Activity will appear after the first upload.</p>
                    </div>
                  ) : null}
                  {activities.map((activity) => (
                    <div className="activity-row" key={activity.activity_id}>
                      <div>
                        <strong>{activity.action}</strong>
                        <p>{activity.filename || "Unnamed item"}</p>
                      </div>
                      <span>{formatDate(activity.created_at)}</span>
                    </div>
                  ))}
                </div>
              </section>
            </aside>
          </div>
        </section>
      </div>
    );
  }

  function renderAdminWorkspace() {
    return (
      <div className="app-shell">
        <aside className="sidebar">
          <div className="sidebar-section side-card">
            <p className="eyebrow">Admin Console</p>
            <strong>{profileLabel}</strong>
            <p className="muted">Operational oversight for users, audit, and service health.</p>
          </div>
          <nav className="sidebar-nav" aria-label="Admin">
            <NavButton active icon="◫" label="Users" onClick={() => void refreshAdminPanel()} disabled={isBusy} />
            <NavButton icon="◪" label="Audit" onClick={() => void refreshAdminPanel()} disabled={isBusy} />
            <NavButton icon="⚠" label="Errors" onClick={() => void refreshAdminPanel()} disabled={isBusy} />
          </nav>
        </aside>

        <section className="workspace">
          <AppTopBar
            profileLabel={profileLabel}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            onSearch={(event) => event.preventDefault()}
            onLogout={() => void logout()}
            isBusy={isBusy}
            title="Admin"
          />

          {error ? <div className="error-banner">{error}</div> : null}

          <div className="workspace-body workspace-body-admin">
            <div className="content-column">
              <section className="summary-grid">
                <article className="surface metric-card">
                  <p className="eyebrow">Users</p>
                  <h2>{adminHealth?.total_users ?? adminUsers.length}</h2>
                  <p className="muted">
                    {adminHealth?.enabled_users ?? 0} enabled • {adminHealth?.admin_users ?? 0} admins
                  </p>
                </article>
                <article className="surface metric-card">
                  <p className="eyebrow">Recent Activity</p>
                  <h2>{adminHealth?.recent_uploads ?? 0}</h2>
                  <p className="muted">
                    Uploads • {adminHealth?.recent_downloads ?? 0} downloads • {adminHealth?.recent_searches ?? 0} searches
                  </p>
                </article>
                <article className="surface metric-card">
                  <p className="eyebrow">Recent Errors</p>
                  <h2>{adminHealth?.recent_errors ?? adminErrors.length}</h2>
                  <p className="muted">Application failures captured by the monitoring pipeline.</p>
                </article>
              </section>

              <section className="surface content-surface">
                <div className="section-header">
                  <div>
                    <p className="eyebrow">User Management</p>
                    <h2>Users</h2>
                  </div>
                  <button className="secondary-button" type="button" onClick={() => void refreshAdminPanel()} disabled={isBusy}>
                    Refresh
                  </button>
                </div>
                {passwordResetResult ? (
                  <div className="notice-card">
                    Temporary password for <strong>{passwordResetResult.username}</strong>:{" "}
                    <code>{passwordResetResult.temporary_password}</code>
                  </div>
                ) : null}
                <div className="table-list">
                  {adminUsers.map((user) => (
                    <div className="table-row admin-row" key={user.user_id}>
                      <div className="table-main">
                        <div className="table-title-row">
                          <strong>{user.username}</strong>
                          <span className={user.enabled ? "status-ok" : "status-bad"}>
                            {user.enabled ? "Enabled" : "Disabled"}
                          </span>
                        </div>
                        <p className="muted">{user.email || "No email"} • Created {formatDate(user.created_at)}</p>
                        <p className="muted">{user.roles.join(", ") || "No roles"}</p>
                      </div>
                      <div className="table-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={isBusy}
                          onClick={() =>
                            void handleAdminAction(() =>
                              user.enabled ? api.disableUser(user.user_id) : api.enableUser(user.user_id),
                            )
                          }
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
              </section>

              <section className="split-grid">
                <article className="surface content-surface">
                  <div className="section-header">
                    <div>
                      <p className="eyebrow">Audit</p>
                      <h2>Audit Events</h2>
                    </div>
                  </div>
                  <div className="table-list">
                    {adminAudit.map((event) => (
                      <div className="table-row compact-row" key={event.event_id}>
                        <div className="table-main">
                          <div className="table-title-row">
                            <strong>{event.event_type}</strong>
                          </div>
                          <p className="muted">{event.message}</p>
                          <p className="muted">
                            {event.actor_username || event.target_username || "Unknown user"}
                            {event.filename ? ` • ${event.filename}` : ""}
                          </p>
                        </div>
                        <span className="table-time">{formatDate(event.created_at)}</span>
                      </div>
                    ))}
                  </div>
                </article>

                <article className="surface content-surface">
                  <div className="section-header">
                    <div>
                      <p className="eyebrow">System</p>
                      <h2>System Health</h2>
                    </div>
                  </div>
                  <div className="table-list">
                    {(adminHealth?.services ?? []).map((service) => (
                      <div className="table-row compact-row" key={service.service}>
                        <div className="table-main">
                          <strong>{service.service}</strong>
                          <p className="muted">{service.detail || "No detail"}</p>
                        </div>
                        <span className={service.status === "healthy" ? "status-ok" : "status-bad"}>
                          {service.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </article>
              </section>

              <section className="surface content-surface">
                <div className="section-header">
                  <div>
                    <p className="eyebrow">Operational Errors</p>
                    <h2>Errors / Low-Level Info</h2>
                  </div>
                </div>
                <div className="table-list">
                  {adminErrors.length === 0 ? (
                    <div className="empty-state empty-state-compact">
                      <strong>No recent errors detected.</strong>
                      <p>The application logs are currently quiet.</p>
                    </div>
                  ) : null}
                  {adminErrors.map((record) => (
                    <div className="table-row compact-row" key={record.event_id}>
                      <div className="table-main">
                        <div className="table-title-row">
                          <strong>{record.service}</strong>
                        </div>
                        <p className="muted">{record.message}</p>
                        <p className="muted">
                          {record.event_name || "application_error"}
                          {record.request_id ? ` • ${record.request_id}` : ""}
                        </p>
                      </div>
                      <span className="table-time">{formatDate(record.created_at)}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (authState === "loading") {
    return (
      <main className="auth-shell">
        <section className="auth-stage">
          <div className="auth-brand-row">
            <div className="brand-mark" aria-hidden="true">
              <span className="brand-mark-blue" />
              <span className="brand-mark-green" />
              <span className="brand-mark-yellow" />
            </div>
            <div>
              <p className="eyebrow">StudyVault</p>
              <h1>Loading StudyVault…</h1>
            </div>
          </div>
          <p className="muted">Preparing your workspace.</p>
        </section>
      </main>
    );
  }

  if (authState === "error") {
    return (
      <main className="auth-shell">
        <section className="auth-stage">
          <div className="auth-brand-row">
            <div className="brand-mark" aria-hidden="true">
              <span className="brand-mark-blue" />
              <span className="brand-mark-green" />
              <span className="brand-mark-yellow" />
            </div>
            <div>
              <p className="eyebrow">StudyVault</p>
              <h1>Authentication setup failed.</h1>
            </div>
          </div>
          {error ? <p className="error-text">{error}</p> : null}
        </section>
      </main>
    );
  }

  if (!authenticated) {
    return (
      <AuthScreen
        title="A Google Drive-style workspace for StudyVault"
        subtitle="Sign in to upload study materials, organize folders, search files and folders, and review recent activity."
        error={error}
      />
    );
  }

  return adminUser ? renderAdminWorkspace() : renderDriveWorkspace();
}
