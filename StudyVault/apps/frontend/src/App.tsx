import {
  type DragEvent as ReactDragEvent,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClient, ApiError, isApiError, isAuthApiError, isPermissionApiError } from "./api/client";
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
type DropTargetKey = "drive-surface" | "trash" | `folder:${string}` | `breadcrumb:${string}` | "breadcrumb:root";
type ContextMenuState = { item: DriveItem; x: number; y: number };
type AdminSection = "users" | "audit" | "errors";
type AdminDataSection = AdminSection | "health";
type DrivePanelMode = "hidden" | "details" | "activity";
type UploadStatus = "queued" | "uploading" | "processing" | "done" | "failed";
type LocalActionError =
  | { scope: "create-folder"; message: string }
  | { scope: "rename"; itemId: string; message: string }
  | { scope: "move"; itemId: string; message: string }
  | null;
type UploadQueueItem = {
  queue_id: string;
  file: File;
  parent_folder_id: string | null;
  destination_label: string;
  tags: string[];
  status: UploadStatus;
  progress: number;
  persisted_file_id?: string;
  error_message?: string;
};

const ROOT_BREADCRUMB: BreadcrumbEntry = { folder_id: null, name: "My Drive" };
const MAX_ACTIVE_UPLOADS = 2;
const DONE_UPLOAD_DISMISS_DELAY_MS = 1500;
const MAX_CLIENT_UPLOAD_BYTES = 99 * 1024 * 1024;
const UPLOAD_WARNING_DISMISS_DELAY_MS = 5000;
const SAFE_ADMIN_ERROR_CONTEXT_KEYS = [
  "service",
  "target_user_id",
  "target_username",
  "requested_limit",
  "max_limit",
  "operation",
] as const;

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

function buildUploadSizeLimitMessage(files: File[]): string {
  const limitLabel = formatBytes(MAX_CLIENT_UPLOAD_BYTES);
  if (files.length === 1) {
    return `${files[0].name} exceeds the current upload limit of ${limitLabel}.`;
  }
  return `${files.length} files exceed the current upload limit of ${limitLabel}.`;
}

function getHealthDetailPreview(detail: string, maxLength = 96): string {
  if (detail.length <= maxLength) {
    return detail;
  }
  return `${detail.slice(0, maxLength).trimEnd()}…`;
}

function buildAdminFailureSummary(failedSections: AdminDataSection[]): string | null {
  if (failedSections.length === 0) {
    return null;
  }
  const labels = failedSections.map((section) => {
    switch (section) {
      case "users":
        return "Users";
      case "audit":
        return "Audit";
      case "health":
        return "Health";
      case "errors":
        return "Errors";
    }
  });
  return `Some admin data could not be refreshed: ${labels.join(", ")}. Displayed data may be incomplete.`;
}

function getSafeAdminContextText(error: ApiError): string | null {
  const safeEntries = SAFE_ADMIN_ERROR_CONTEXT_KEYS.flatMap((key) => {
    const value = error.context[key];
    return value === undefined || value === null ? [] : [[key, String(value)] as const];
  });
  if (safeEntries.length === 0) {
    return null;
  }
  return safeEntries
    .map(([key, value]) => {
      switch (key) {
        case "service":
          return `Service ${value}`;
        case "target_username":
          return `User ${value}`;
        case "target_user_id":
          return `User id ${value}`;
        case "requested_limit":
          return `Requested limit ${value}`;
        case "max_limit":
          return `Max limit ${value}`;
        case "operation":
          return `Operation ${value}`;
      }
    })
    .join(" • ");
}

function getAdminErrorMessage(error: unknown, fallback: string): string {
  if (isApiError(error)) {
    const contextText = getSafeAdminContextText(error);
    switch (error.code) {
      case "service_unavailable":
      case "storage_unavailable":
        return contextText
          ? `${error.message}. ${contextText}. Try again in a moment.`
          : `${error.message}. Try again in a moment.`;
      case "admin_access_required":
        return "You no longer have permission to perform this admin action.";
      default:
        return contextText ? `${error.message}. ${contextText}.` : error.message;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

function buildDriveItemPath(breadcrumbs: BreadcrumbEntry[], item: DriveItem): string {
  return [...breadcrumbs.map((entry) => entry.name), item.name].join(" / ");
}

function getSearchErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "search_query_too_long") {
      return error.message;
    }
    if (error.category === "unavailable") {
      return "Search is temporarily unavailable. Try again in a moment.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Search failed";
}

function getUploadErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "upload_empty_file") {
      return "This file is empty. Choose a file with content before uploading.";
    }
    if (error.code === "upload_size_exceeded") {
      return "This file is too large for the current upload limit.";
    }
    if (error.code === "storage_unavailable") {
      return "File storage is temporarily unavailable. Retry the upload in a moment.";
    }
    if (error.code === "downstream_sync_failed") {
      return "The file was stored, but metadata sync failed. Retry to restore a consistent view.";
    }
    if (error.code === "upload_network_error") {
      return "Upload could not reach the server. Check your connection and try again.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Upload failed";
}

function getAuthRecoveryMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "missing_bearer_token" || error.code === "invalid_token" || error.code === "unknown_signing_key") {
      return "Your session expired or became invalid. Sign in again.";
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Your session expired. Sign in again.";
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
  className?: string;
  onDragOver?: (event: ReactDragEvent<HTMLButtonElement>) => void;
  onDragLeave?: (event: ReactDragEvent<HTMLButtonElement>) => void;
  onDrop?: (event: ReactDragEvent<HTMLButtonElement>) => void;
  hideLabel?: boolean;
}) {
  const {
    active = false,
    icon,
    label,
    onClick,
    disabled = false,
    className = "",
    onDragOver,
    onDragLeave,
    onDrop,
    hideLabel = false,
  } = props;
  const classes = [active ? "nav-button nav-button-active" : "nav-button", className]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      className={classes}
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      aria-label={hideLabel ? label : undefined}
      title={label}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <span className="nav-icon" aria-hidden="true">
        {icon}
      </span>
      {!hideLabel ? <span>{label}</span> : null}
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
  secondaryActionLabel?: string;
  secondaryActionActive?: boolean;
  onSecondaryAction?: () => void;
}) {
  const {
    profileLabel,
    searchQuery,
    onSearchQueryChange,
    onSearch,
    onLogout,
    isBusy,
    title,
    secondaryActionLabel,
    secondaryActionActive = false,
    onSecondaryAction,
  } = props;

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
        {secondaryActionLabel && onSecondaryAction ? (
          <button
            className={secondaryActionActive ? "secondary-button topbar-toggle-active" : "secondary-button"}
            type="button"
            onClick={onSecondaryAction}
            disabled={isBusy}
            aria-pressed={secondaryActionActive}
          >
            {secondaryActionLabel}
          </button>
        ) : null}
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
  const [adminPartialRefreshWarning, setAdminPartialRefreshWarning] = useState<string | null>(null);
  const [adminSectionErrors, setAdminSectionErrors] = useState<Partial<Record<AdminDataSection, string>>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[]>([]);
  const [uploadQueue, setUploadQueue] = useState<UploadQueueItem[]>([]);
  const [uploadFormError, setUploadFormError] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [renameItem, setRenameItem] = useState<DriveItem | null>(null);
  const [renameName, setRenameName] = useState("");
  const [moveItem, setMoveItem] = useState<DriveItem | null>(null);
  const [moveTargetFolderId, setMoveTargetFolderId] = useState<string>("");
  const [showCreateFolderForm, setShowCreateFolderForm] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [draggedItem, setDraggedItem] = useState<DriveItem | null>(null);
  const [activeDropTarget, setActiveDropTarget] = useState<DropTargetKey | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [passwordResetResult, setPasswordResetResult] = useState<AdminPasswordResetResult | null>(null);
  const [activeAdminSection, setActiveAdminSection] = useState<AdminSection>("users");
  const [expandedHealthDetails, setExpandedHealthDetails] = useState<Record<string, boolean>>({});
  const [selectedDriveItem, setSelectedDriveItem] = useState<DriveItem | null>(null);
  const [drivePanelMode, setDrivePanelMode] = useState<DrivePanelMode>("hidden");
  const [localActionError, setLocalActionError] = useState<LocalActionError>(null);
  const [searchFormError, setSearchFormError] = useState<string | null>(null);
  const [searchModeActive, setSearchModeActive] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const suppressFolderOpenUntilRef = useRef(0);
  const pendingAdminSectionRef = useRef<AdminSection | null>(null);
  const pendingAdminSectionTimeoutRef = useRef<number | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const currentFolderIdRef = useRef<string | null>(null);
  const currentViewRef = useRef<DashboardView>("drive");
  const inFlightUploadIdsRef = useRef<Set<string>>(new Set());
  const uploadDismissTimeoutsRef = useRef<Map<string, number>>(new Map());
  const uploadWarningTimeoutRef = useRef<number | null>(null);
  const adminUsersSectionRef = useRef<HTMLElement | null>(null);
  const adminAuditSectionRef = useRef<HTMLElement | null>(null);
  const adminErrorsSectionRef = useRef<HTMLElement | null>(null);

  const currentFolderLabel = breadcrumbs[breadcrumbs.length - 1]?.name ?? ROOT_BREADCRUMB.name;
  const canGoUp = breadcrumbs.length > 1;
  const driveCountLabel =
    currentView === "drive"
      ? `${currentItems.length} item${currentItems.length === 1 ? "" : "s"}`
      : `${trashItems.length} item${trashItems.length === 1 ? "" : "s"}`;
  const activeUploadCount = uploadQueue.filter(
    (item) => item.status === "uploading" || item.status === "processing",
  ).length;

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

  useEffect(() => {
    currentFolderIdRef.current = currentFolderId;
  }, [currentFolderId]);

  useEffect(() => {
    currentViewRef.current = currentView;
  }, [currentView]);

  useEffect(() => {
    if (!contextMenu) {
      return;
    }

    function handlePointerDown() {
      setContextMenu(null);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setContextMenu(null);
      }
    }

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [contextMenu]);

  async function loadFolder(folderId: string | null) {
    const catalogPromise = api.listCatalogItems(folderId);
    const breadcrumbsPromise =
      folderId === null ? Promise.resolve({ breadcrumbs: [ROOT_BREADCRUMB] }) : api.getBreadcrumbs(folderId);
    const [catalogPayload, breadcrumbPayload, activityPayload] = await Promise.all([
      catalogPromise,
      breadcrumbsPromise,
      loadActivitiesBestEffort(),
    ]);
    startTransition(() => {
      setCurrentFolderId(folderId);
      setCurrentView("drive");
      setBreadcrumbs(breadcrumbPayload.breadcrumbs);
      setCurrentItems(catalogPayload.items);
      if (activityPayload !== null) {
        setActivities(activityPayload);
      }
      setContextMenu(null);
      setActiveDropTarget(null);
      setSelectedDriveItem(null);
      setDrivePanelMode("hidden");
      setLocalActionError(null);
      setSearchModeActive(false);
      setSearchResults([]);
    });
  }

  async function loadTrash() {
    const [trashPayload, activityPayload] = await Promise.all([api.listTrash(), loadActivitiesBestEffort()]);
    startTransition(() => {
      setCurrentView("trash");
      setTrashItems(trashPayload.items);
      if (activityPayload !== null) {
        setActivities(activityPayload);
      }
      setContextMenu(null);
      setActiveDropTarget(null);
      setSelectedDriveItem(null);
      setDrivePanelMode("hidden");
      setLocalActionError(null);
      setSearchModeActive(false);
      setSearchResults([]);
    });
  }

  async function refreshAdminPanel() {
    const results = await Promise.allSettled([
      api.listAdminUsers(),
      api.listAdminAudit(),
      api.getAdminHealth(),
      api.listAdminErrors(),
    ]);

    const firstAuthFailure = results.find(
      (result) => result.status === "rejected" && isAuthApiError(result.reason),
    );
    if (firstAuthFailure && firstAuthFailure.status === "rejected") {
      throw firstAuthFailure.reason;
    }

    const [usersPayload, auditPayload, healthPayload, errorsPayload] = results;
    const nextSectionErrors: Partial<Record<AdminDataSection, string>> = {};
    const failedSections: AdminDataSection[] = [];

    if (usersPayload.status === "rejected") {
      nextSectionErrors.users = getAdminErrorMessage(usersPayload.reason, "Users could not be refreshed.");
      failedSections.push("users");
    }
    if (auditPayload.status === "rejected") {
      nextSectionErrors.audit = getAdminErrorMessage(auditPayload.reason, "Audit events could not be refreshed.");
      failedSections.push("audit");
    }
    if (healthPayload.status === "rejected") {
      nextSectionErrors.health = getAdminErrorMessage(healthPayload.reason, "Health summary could not be refreshed.");
      failedSections.push("health");
    }
    if (errorsPayload.status === "rejected") {
      nextSectionErrors.errors = getAdminErrorMessage(errorsPayload.reason, "Error records could not be refreshed.");
      failedSections.push("errors");
    }

    startTransition(() => {
      if (usersPayload.status === "fulfilled") {
        setAdminUsers(usersPayload.value);
      }
      if (auditPayload.status === "fulfilled") {
        setAdminAudit(auditPayload.value);
      }
      if (healthPayload.status === "fulfilled") {
        setAdminHealth(healthPayload.value);
      }
      if (errorsPayload.status === "fulfilled") {
        setAdminErrors(errorsPayload.value);
      }
      setAdminSectionErrors(nextSectionErrors);
      setAdminPartialRefreshWarning(buildAdminFailureSummary(failedSections));
    });
  }

  function scrollToAdminSection(section: AdminSection) {
    const targets: Record<AdminSection, HTMLElement | null> = {
      users: adminUsersSectionRef.current,
      audit: adminAuditSectionRef.current,
      errors: adminErrorsSectionRef.current,
    };
    if (pendingAdminSectionTimeoutRef.current !== null) {
      window.clearTimeout(pendingAdminSectionTimeoutRef.current);
    }
    pendingAdminSectionRef.current = section;
    pendingAdminSectionTimeoutRef.current = window.setTimeout(() => {
      pendingAdminSectionRef.current = null;
      pendingAdminSectionTimeoutRef.current = null;
    }, 1200);
    setActiveAdminSection(section);
    targets[section]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function toggleHealthDetail(serviceName: string) {
    setExpandedHealthDetails((current) => ({
      ...current,
      [serviceName]: !current[serviceName],
    }));
  }

  function showDriveItemDetails(item: DriveItem) {
    setSelectedDriveItem(item);
    setDrivePanelMode("details");
    setContextMenu(null);
  }

  function toggleDriveActivityPanel() {
    setDrivePanelMode((current) => (current === "activity" ? "hidden" : "activity"));
  }

  function clearSearchMode() {
    setSearchResults([]);
    setSearchModeActive(false);
    setSearchFormError(null);
  }

  function parseTagInput(value: string): string[] {
    return value
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  function enqueueUploadFiles(
    files: File[],
    parentFolderId: string | null,
    destinationLabel: string,
    tags: string[],
  ) {
    if (files.length === 0) {
      return false;
    }

    const acceptedFiles = files.filter((file) => file.size <= MAX_CLIENT_UPLOAD_BYTES);
    const oversizedFiles = files.filter((file) => file.size > MAX_CLIENT_UPLOAD_BYTES);

    if (acceptedFiles.length === 0) {
      setUploadFormError(buildUploadSizeLimitMessage(oversizedFiles));
      return false;
    }

    setUploadQueue((current) => [
      ...current,
      ...acceptedFiles.map((file) => ({
        queue_id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
        file,
        parent_folder_id: parentFolderId,
        destination_label: destinationLabel,
        tags,
        status: "queued" as const,
        progress: 0,
      })),
    ]);
    setUploadFormError(oversizedFiles.length > 0 ? buildUploadSizeLimitMessage(oversizedFiles) : null);
    setError(null);
    return true;
  }

  function enterAuthRecovery(error: unknown) {
    startTransition(() => {
      setAuthenticated(false);
      setAdminUser(false);
      setAdminPartialRefreshWarning(null);
      setCurrentView("drive");
      setCurrentFolderId(null);
      setBreadcrumbs([ROOT_BREADCRUMB]);
      setCurrentItems([]);
      setTrashItems([]);
      setSearchResults([]);
      setSearchModeActive(false);
      setSearchFormError(null);
      setAdminSectionErrors({});
      setSelectedDriveItem(null);
      setDrivePanelMode("hidden");
      setContextMenu(null);
      setActiveDropTarget(null);
      setMoveItem(null);
      setRenameItem(null);
      setLocalActionError(null);
      setUploadFormError(null);
      setError(getAuthRecoveryMessage(error));
    });
  }

  function handleApiFailure(error: unknown, fallback: string): string | null {
    if (isAuthApiError(error)) {
      enterAuthRecovery(error);
      return null;
    }
    if (isPermissionApiError(error)) {
      return error.message;
    }
    if (isApiError(error)) {
      return error.message;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return fallback;
  }

  async function loadActivitiesBestEffort(): Promise<ActivityRecord[] | null> {
    try {
      return await api.listActivity();
    } catch (activityError) {
      if (isAuthApiError(activityError)) {
        throw activityError;
      }
      return null;
    }
  }

  async function refreshActivitiesBestEffort(): Promise<void> {
    const latestActivity = await loadActivitiesBestEffort();
    if (latestActivity !== null) {
      startTransition(() => {
        setActivities(latestActivity);
      });
    }
  }

  function hasExternalFiles(event: ReactDragEvent<HTMLElement>): boolean {
    if (draggedItem) {
      return false;
    }
    const types = Array.from(event.dataTransfer.types ?? []);
    return types.includes("Files") && event.dataTransfer.files.length > 0;
  }

  function getDroppedFiles(event: ReactDragEvent<HTMLElement>): File[] {
    return Array.from(event.dataTransfer.files ?? []);
  }

  function clearUploadDismissTimeout(queueId: string) {
    const timeoutId = uploadDismissTimeoutsRef.current.get(queueId);
    if (timeoutId === undefined) {
      return;
    }
    window.clearTimeout(timeoutId);
    uploadDismissTimeoutsRef.current.delete(queueId);
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
            const message = handleApiFailure(dashboardError, "Workspace bootstrap failed");
            if (message) {
              setError(message);
            }
          }
        }
      } catch (bootstrapError) {
        setAuthState("error");
        setError(bootstrapError instanceof Error ? bootstrapError.message : String(bootstrapError));
      }
    }

    void bootstrap();
  }, []);

  useEffect(() => {
    if (!adminUser) {
      return;
    }

    const sections: Array<{ key: AdminSection; element: HTMLElement | null }> = [
      { key: "users", element: adminUsersSectionRef.current },
      { key: "audit", element: adminAuditSectionRef.current },
      { key: "errors", element: adminErrorsSectionRef.current },
    ];
    const visibleSections = sections.filter((section) => section.element !== null);
    if (visibleSections.length === 0) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleEntry = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        if (!visibleEntry) {
          return;
        }
        const nextSection = visibleSections.find((section) => section.element === visibleEntry.target);
        if (nextSection) {
          const pendingSection = pendingAdminSectionRef.current;
          if (pendingSection && nextSection.key !== pendingSection) {
            return;
          }
          if (pendingSection === nextSection.key) {
            pendingAdminSectionRef.current = null;
            if (pendingAdminSectionTimeoutRef.current !== null) {
              window.clearTimeout(pendingAdminSectionTimeoutRef.current);
              pendingAdminSectionTimeoutRef.current = null;
            }
          }
          setActiveAdminSection((current) => (current === nextSection.key ? current : nextSection.key));
        }
      },
      {
        root: null,
        threshold: [0.2, 0.45, 0.7],
        rootMargin: "-100px 0px -45% 0px",
      },
    );

    for (const section of visibleSections) {
      observer.observe(section.element!);
    }

    return () => {
      observer.disconnect();
      if (pendingAdminSectionTimeoutRef.current !== null) {
        window.clearTimeout(pendingAdminSectionTimeoutRef.current);
        pendingAdminSectionTimeoutRef.current = null;
      }
      pendingAdminSectionRef.current = null;
    };
  }, [adminUser]);

  useEffect(() => {
    if (!authenticated || adminUser) {
      return;
    }

    function handleWindowFileDrag(event: DragEvent) {
      if (draggedItem !== null) {
        return;
      }
      const dataTransfer = event.dataTransfer;
      const types = Array.from(dataTransfer?.types ?? []);
      const hasFileDrag = types.includes("Files") || (dataTransfer?.files.length ?? 0) > 0;
      if (!hasFileDrag) {
        return;
      }
      event.preventDefault();
      if (event.type === "dragover" && dataTransfer) {
        dataTransfer.dropEffect = "copy";
      }
    }

    window.addEventListener("dragover", handleWindowFileDrag);
    window.addEventListener("drop", handleWindowFileDrag);
    return () => {
      window.removeEventListener("dragover", handleWindowFileDrag);
      window.removeEventListener("drop", handleWindowFileDrag);
    };
  }, [adminUser, authenticated, draggedItem]);

  useEffect(() => {
    const availableSlots = MAX_ACTIVE_UPLOADS - activeUploadCount;
    if (availableSlots <= 0) {
      return;
    }

    const queuedItems = uploadQueue
      .filter((item) => item.status === "queued" && !inFlightUploadIdsRef.current.has(item.queue_id))
      .slice(0, availableSlots);
    for (const item of queuedItems) {
      inFlightUploadIdsRef.current.add(item.queue_id);
      void processUploadQueueItem(item);
    }
  }, [activeUploadCount, uploadQueue]);

  useEffect(() => {
    const doneIds = new Set(uploadQueue.filter((item) => item.status === "done").map((item) => item.queue_id));

    for (const item of uploadQueue) {
      if (item.status === "done" && !uploadDismissTimeoutsRef.current.has(item.queue_id)) {
        const timeoutId = window.setTimeout(() => {
          uploadDismissTimeoutsRef.current.delete(item.queue_id);
          dismissUpload(item.queue_id);
        }, DONE_UPLOAD_DISMISS_DELAY_MS);
        uploadDismissTimeoutsRef.current.set(item.queue_id, timeoutId);
      }
      if (item.status !== "done") {
        clearUploadDismissTimeout(item.queue_id);
      }
    }

    for (const [queueId, timeoutId] of uploadDismissTimeoutsRef.current.entries()) {
      if (!doneIds.has(queueId)) {
        window.clearTimeout(timeoutId);
        uploadDismissTimeoutsRef.current.delete(queueId);
      }
    }
  }, [uploadQueue]);

  useEffect(() => {
    return () => {
      for (const timeoutId of uploadDismissTimeoutsRef.current.values()) {
        window.clearTimeout(timeoutId);
      }
      uploadDismissTimeoutsRef.current.clear();
      if (uploadWarningTimeoutRef.current !== null) {
        window.clearTimeout(uploadWarningTimeoutRef.current);
        uploadWarningTimeoutRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!uploadFormError) {
      if (uploadWarningTimeoutRef.current !== null) {
        window.clearTimeout(uploadWarningTimeoutRef.current);
        uploadWarningTimeoutRef.current = null;
      }
      return;
    }

    if (uploadWarningTimeoutRef.current !== null) {
      window.clearTimeout(uploadWarningTimeoutRef.current);
    }
    uploadWarningTimeoutRef.current = window.setTimeout(() => {
      setUploadFormError(null);
      uploadWarningTimeoutRef.current = null;
    }, UPLOAD_WARNING_DISMISS_DELAY_MS);

    return () => {
      if (uploadWarningTimeoutRef.current !== null) {
        window.clearTimeout(uploadWarningTimeoutRef.current);
        uploadWarningTimeoutRef.current = null;
      }
    };
  }, [uploadFormError]);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      clearSearchMode();
      setError(null);
      return;
    }

    try {
      setIsBusy(true);
      setSearchFormError(null);
      const payload = await api.search(searchQuery.trim(), { kind: "all" });
      startTransition(() => {
        setSearchResults(payload);
        setSearchModeActive(true);
      });
      setError(null);
    } catch (searchError) {
      if (isAuthApiError(searchError)) {
        enterAuthRecovery(searchError);
      } else {
        setSearchFormError(getSearchErrorMessage(searchError));
      }
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingUploadFiles.length === 0) {
      setUploadFormError("Choose at least one file before uploading.");
      return;
    }

    setUploadFormError(null);
    enqueueUploadFiles(pendingUploadFiles, currentFolderId, currentFolderLabel, parseTagInput(tagInput));
    setPendingUploadFiles([]);
    if (uploadInputRef.current) {
      uploadInputRef.current.value = "";
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
      const message = handleApiFailure(trashError, "Move to trash failed");
      if (message) {
        setError(message);
      }
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = newFolderName.trim();
    if (!trimmedName) {
      setLocalActionError({ scope: "create-folder", message: "Enter a folder name." });
      return;
    }

    try {
      setIsBusy(true);
      setLocalActionError(null);
      setError(null);
      await api.createFolder(trimmedName, currentFolderId);
      setNewFolderName("");
      setShowCreateFolderForm(false);
      await loadFolder(currentFolderId);
      setError(null);
    } catch (createFolderError) {
      const message = handleApiFailure(createFolderError, "Folder creation failed");
      if (message) {
        setLocalActionError({
          scope: "create-folder",
          message,
        });
      }
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
      setLocalActionError({ scope: "rename", itemId: renameItem.item_id, message: "Enter a name." });
      return;
    }

    try {
      setIsBusy(true);
      setLocalActionError(null);
      setError(null);
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
      const message = handleApiFailure(renameError, "Rename failed");
      if (message) {
        setLocalActionError({
          scope: "rename",
          itemId: renameItem.item_id,
          message,
        });
      }
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
      setLocalActionError(null);
      setError(null);
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
      const message = handleApiFailure(moveError, "Move failed");
      if (message) {
        setLocalActionError({
          scope: "move",
          itemId: moveItem.item_id,
          message,
        });
      }
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
      const message = handleApiFailure(restoreError, "Restore failed");
      if (message) {
        setError(message);
      }
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
      const message = handleApiFailure(downloadError, "Download failed");
      if (message) {
        setError(message);
      }
    } finally {
      setIsBusy(false);
    }
  }

  function clearDragState() {
    setDraggedItem(null);
    setActiveDropTarget(null);
  }

  function isSameParentTarget(item: DriveItem, targetFolderId: string | null): boolean {
    return (item.parent_folder_id ?? null) === targetFolderId;
  }

  function canDropIntoFolder(item: DriveItem | null, targetFolderId: string): boolean {
    if (!item) {
      return false;
    }
    if (item.kind === "folder" && item.item_id === targetFolderId) {
      return false;
    }
    return !isSameParentTarget(item, targetFolderId);
  }

  function canDropIntoParent(item: DriveItem | null, targetFolderId: string | null): boolean {
    if (!item) {
      return false;
    }
    return !isSameParentTarget(item, targetFolderId);
  }

  function canDropIntoTrash(item: DriveItem | null): boolean {
    return item !== null;
  }

  function handleDragStart(item: DriveItem) {
    suppressFolderOpenUntilRef.current = Date.now() + 250;
    setDraggedItem(item);
    setActiveDropTarget(null);
    setContextMenu(null);
    setRenameItem(null);
    setRenameName("");
    setMoveItem(null);
    setMoveTargetFolderId("");
    setError(null);
  }

  function handleDragEnd() {
    suppressFolderOpenUntilRef.current = Date.now() + 250;
    clearDragState();
  }

  function shouldIgnoreRowClick(event: ReactMouseEvent<HTMLElement>): boolean {
    const target = event.target as HTMLElement | null;
    return Boolean(target?.closest("button, input, select, option, textarea, form, label, a"));
  }

  function handleDriveRowClick(event: ReactMouseEvent<HTMLElement>, item: DriveItem) {
    if (shouldIgnoreRowClick(event)) {
      return;
    }
    showDriveItemDetails(item);
  }

  function handleDriveRowDoubleClick(event: ReactMouseEvent<HTMLElement>, item: DriveItem) {
    if (item.kind !== "folder" || shouldIgnoreRowClick(event)) {
      return;
    }
    void handleOpenFolder(item);
  }

  function handleDropTargetOver(
    event: ReactDragEvent<HTMLElement>,
    targetKey: DropTargetKey,
    canDrop: boolean,
  ) {
    if (!canDrop || isBusy) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (activeDropTarget !== targetKey) {
      setActiveDropTarget(targetKey);
    }
  }

  function handleDropTargetLeave(targetKey: DropTargetKey) {
    if (activeDropTarget === targetKey) {
      setActiveDropTarget(null);
    }
  }

  function handleDriveSurfaceDragOver(event: ReactDragEvent<HTMLElement>) {
    if (isBusy || !hasExternalFiles(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    if (activeDropTarget !== "drive-surface") {
      setActiveDropTarget("drive-surface");
    }
  }

  function handleDriveSurfaceDragLeave(event: ReactDragEvent<HTMLElement>) {
    if (activeDropTarget !== "drive-surface") {
      return;
    }
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setActiveDropTarget(null);
  }

  function handleDriveSurfaceDrop(event: ReactDragEvent<HTMLElement>) {
    if (!hasExternalFiles(event)) {
      return;
    }
    event.preventDefault();
    const droppedFiles = getDroppedFiles(event);
    setActiveDropTarget(null);
    if (droppedFiles.length === 0) {
      return;
    }
    enqueueUploadFiles(droppedFiles, currentFolderId, currentFolderLabel, parseTagInput(tagInput));
  }

  function handleExternalUploadDrop(
    event: ReactDragEvent<HTMLElement>,
    targetFolderId: string | null,
    destinationLabel: string,
  ) {
    if (!hasExternalFiles(event)) {
      return false;
    }
    event.preventDefault();
    event.stopPropagation();
    const droppedFiles = getDroppedFiles(event);
    setActiveDropTarget(null);
    if (droppedFiles.length === 0) {
      return true;
    }
    enqueueUploadFiles(droppedFiles, targetFolderId, destinationLabel, parseTagInput(tagInput));
    return true;
  }

  async function moveDraggedItemTo(targetFolderId: string | null) {
    if (!draggedItem || isSameParentTarget(draggedItem, targetFolderId)) {
      clearDragState();
      return;
    }

    try {
      setIsBusy(true);
      if (draggedItem.kind === "folder") {
        await api.moveFolder(draggedItem.item_id, targetFolderId);
      } else {
        await api.moveFile(draggedItem.item_id, targetFolderId);
      }
      await loadFolder(currentFolderId);
      setError(null);
    } catch (moveError) {
      const message = handleApiFailure(moveError, "Move failed");
      if (message) {
        setError(message);
      }
    } finally {
      clearDragState();
      setIsBusy(false);
    }
  }

  async function trashDraggedItem() {
    if (!draggedItem) {
      clearDragState();
      return;
    }

    try {
      setIsBusy(true);
      if (draggedItem.kind === "folder") {
        await api.trashFolder(draggedItem.item_id);
      } else {
        await api.trashFile(draggedItem.item_id);
      }
      await loadFolder(currentFolderId);
      setError(null);
    } catch (trashError) {
      const message = handleApiFailure(trashError, "Move to trash failed");
      if (message) {
        setError(message);
      }
    } finally {
      clearDragState();
      setIsBusy(false);
    }
  }

  function handleRowContextMenu(event: ReactMouseEvent<HTMLElement>, item: DriveItem) {
    event.preventDefault();
    setContextMenu({ item, x: event.clientX, y: event.clientY });
    setError(null);
  }

  function handleContextMenuTriggerClick(
    event: ReactMouseEvent<HTMLButtonElement>,
    item: DriveItem,
  ) {
    event.stopPropagation();
    const bounds = event.currentTarget.getBoundingClientRect();
    setContextMenu({ item, x: bounds.right - 8, y: bounds.bottom + 8 });
    setError(null);
  }

  function openRenameFromMenu(item: DriveItem) {
    setContextMenu(null);
    showDriveItemDetails(item);
    handleStartRename(item);
  }

  function openMoveFromMenu(item: DriveItem) {
    setContextMenu(null);
    showDriveItemDetails(item);
    handleStartMove(item);
  }

  function handleStartRename(item: DriveItem) {
    setMoveItem(null);
    setMoveTargetFolderId("");
    setRenameItem(item);
    setRenameName(item.name);
    setLocalActionError(null);
    setError(null);
  }

  function handleCancelRename() {
    setRenameItem(null);
    setRenameName("");
    setLocalActionError(null);
    setError(null);
  }

  function handleStartMove(item: DriveItem) {
    setRenameItem(null);
    setRenameName("");
    setMoveItem(item);
    setMoveTargetFolderId(item.parent_folder_id ?? "");
    setLocalActionError(null);
    setError(null);
  }

  function handleCancelMove() {
    setMoveItem(null);
    setMoveTargetFolderId("");
    setLocalActionError(null);
    setError(null);
  }

  async function handleOpenDrive() {
    try {
      setIsBusy(true);
      await loadFolder(currentFolderId);
      setError(null);
    } catch (navigationError) {
      const message = handleApiFailure(navigationError, "Drive load failed");
      if (message) {
        setError(message);
      }
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
      const message = handleApiFailure(navigationError, "Trash load failed");
      if (message) {
        setError(message);
      }
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
      const message = handleApiFailure(navigationError, "Folder load failed");
      if (message) {
        setError(message);
      }
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
      const message = handleApiFailure(navigationError, "Folder load failed");
      if (message) {
        setError(message);
      }
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
      const message = handleApiFailure(navigationError, "Folder load failed");
      if (message) {
        setError(message);
      }
    } finally {
      setIsBusy(false);
    }
  }

  async function handleAdminAction(action: () => Promise<unknown>) {
    try {
      setIsBusy(true);
      setPasswordResetResult(null);
      setError(null);
      await action();
      await refreshAdminPanel();
      setError(null);
      setAdminSectionErrors((current) => ({ ...current, users: undefined }));
    } catch (actionError) {
      if (isAuthApiError(actionError)) {
        enterAuthRecovery(actionError);
      } else {
        setAdminSectionErrors((current) => ({
          ...current,
          users: getAdminErrorMessage(actionError, "Admin action failed."),
        }));
      }
    } finally {
      setIsBusy(false);
    }
  }

  async function handlePasswordReset(userId: string) {
    try {
      setIsBusy(true);
      setError(null);
      const result = await api.resetPassword(userId);
      setPasswordResetResult(result);
      await refreshAdminPanel();
      setError(null);
      setAdminSectionErrors((current) => ({ ...current, users: undefined }));
    } catch (actionError) {
      if (isAuthApiError(actionError)) {
        enterAuthRecovery(actionError);
      } else {
        setAdminSectionErrors((current) => ({
          ...current,
          users: getAdminErrorMessage(actionError, "Password reset failed."),
        }));
      }
    } finally {
      setIsBusy(false);
    }
  }

  function updateUploadQueueItem(queueId: string, updater: (item: UploadQueueItem) => UploadQueueItem) {
    setUploadQueue((current) =>
      current.map((item) => (item.queue_id === queueId ? updater(item) : item)),
    );
  }

  async function processUploadQueueItem(item: UploadQueueItem) {
    updateUploadQueueItem(item.queue_id, (current) => ({
      ...current,
      status: "uploading",
      progress: current.progress > 0 ? current.progress : 0,
      error_message: undefined,
    }));

    try {
      const uploaded = await api.uploadFileWithProgress(item.file, item.tags, item.parent_folder_id, {
        onProgress: (percent) => {
          updateUploadQueueItem(item.queue_id, (current) => ({
            ...current,
            status: current.status === "processing" ? "processing" : "uploading",
            progress: percent,
          }));
        },
        onProcessing: () => {
          updateUploadQueueItem(item.queue_id, (current) => ({
            ...current,
            status: "processing",
            progress: 100,
          }));
        },
      });

      updateUploadQueueItem(item.queue_id, (current) => ({
        ...current,
        status: "done",
        progress: 100,
        persisted_file_id: uploaded.file_id,
        error_message: undefined,
      }));

      let refreshError: unknown = null;
      if (
        currentViewRef.current === "drive" &&
        (item.parent_folder_id ?? null) === (currentFolderIdRef.current ?? null)
      ) {
        try {
          await loadFolder(currentFolderIdRef.current);
        } catch (postUploadRefreshError) {
          refreshError = postUploadRefreshError;
        }
      } else {
        try {
          await refreshActivitiesBestEffort();
        } catch (postUploadRefreshError) {
          refreshError = postUploadRefreshError;
        }
      }
      if (refreshError) {
        const message = handleApiFailure(refreshError, "Upload completed, but the workspace could not be refreshed.");
        if (message) {
          setError(message);
        }
      } else {
        setError(null);
      }
    } catch (uploadError) {
      if (isAuthApiError(uploadError)) {
        enterAuthRecovery(uploadError);
      }
      updateUploadQueueItem(item.queue_id, (current) => ({
        ...current,
        status: "failed",
        error_message: getUploadErrorMessage(uploadError),
      }));
    } finally {
      inFlightUploadIdsRef.current.delete(item.queue_id);
    }
  }

  function retryUpload(queueId: string) {
    clearUploadDismissTimeout(queueId);
    updateUploadQueueItem(queueId, (item) => ({
      ...item,
      status: "queued",
      progress: 0,
      error_message: undefined,
    }));
    setError(null);
  }

  function dismissUpload(queueId: string) {
    clearUploadDismissTimeout(queueId);
    setUploadQueue((current) => current.filter((item) => item.queue_id !== queueId));
  }

  function renderSearchResults() {
    if (!searchModeActive) {
      return null;
    }

    return (
      <section className="surface content-surface">
        <div className="section-header">
          <div>
            <p className="eyebrow">Search</p>
            <h2>Search Results</h2>
          </div>
          <div className="section-header-actions">
            <span className="section-meta">
              {searchResults.length} match{searchResults.length === 1 ? "" : "es"}
            </span>
            <button
              className="secondary-button"
              type="button"
              onClick={() => {
                setSearchQuery("");
                clearSearchMode();
              }}
            >
              Close Search
            </button>
          </div>
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
                  <strong title={item.name}>{item.name}</strong>
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

  function renderUploadQueue() {
    if (currentView !== "drive" || (uploadQueue.length === 0 && !uploadFormError)) {
      return null;
    }

    return (
      <section className="upload-queue-panel" aria-label="Upload Queue">
        <div className="section-header section-header-compact">
          <div>
            <p className="eyebrow">Uploads</p>
            <h3>Upload Queue</h3>
          </div>
          <span className="section-meta">
            {activeUploadCount} active / {uploadQueue.length} total
          </span>
        </div>
        {uploadFormError ? <div className="error-banner">{uploadFormError}</div> : null}
        <div className="upload-queue-list">
          {uploadQueue.map((item) => (
            <div className={`upload-queue-row upload-status-${item.status}`} key={item.queue_id}>
              <div className="upload-queue-main">
                <div className="upload-queue-title-row">
                  <strong title={item.file.name}>{item.file.name}</strong>
                  <span className="upload-status-pill">{item.status}</span>
                </div>
                <p className="muted">
                  Destination: {item.destination_label}
                  {item.tags.length > 0 ? ` • Tags: ${item.tags.join(", ")}` : ""}
                </p>
                {item.status === "uploading" || item.status === "processing" ? (
                  <div className="upload-progress-block">
                    <div
                      className="upload-progress-bar"
                      aria-hidden="true"
                      style={{ ["--upload-progress" as string]: `${item.progress}%` }}
                    />
                    <span className="upload-progress-label">
                      {item.status === "processing" ? "Processing…" : `${item.progress}% uploaded`}
                    </span>
                  </div>
                ) : null}
                {item.status === "done" ? <p className="muted">Upload finished.</p> : null}
                {item.status === "failed" && item.error_message ? (
                  <p className="error-text">Upload failed: {item.error_message}</p>
                ) : null}
              </div>
              <div className="table-actions table-actions-inline">
                {item.status === "failed" ? (
                  <button className="secondary-button" type="button" onClick={() => retryUpload(item.queue_id)}>
                    Retry
                  </button>
                ) : null}
                {item.status === "failed" || item.status === "done" ? (
                  <button className="secondary-button" type="button" onClick={() => dismissUpload(item.queue_id)}>
                    Dismiss
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  }

  function renderDriveRows(items: DriveItem[]) {
    return items.map((item) => (
      <div
        className={[
          "drive-tile",
          selectedDriveItem?.item_id === item.item_id && drivePanelMode === "details" ? "drive-tile-selected" : "",
          draggedItem?.item_id === item.item_id ? "drive-tile-dragging" : "",
          item.kind === "folder" && activeDropTarget === `folder:${item.item_id}` ? "drive-tile-drop-target" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        key={item.item_id}
        draggable={!isBusy}
        onDragStart={() => handleDragStart(item)}
        onDragEnd={handleDragEnd}
        onContextMenu={(event) => handleRowContextMenu(event, item)}
        onClick={(event) => handleDriveRowClick(event, item)}
        onDoubleClick={(event) => handleDriveRowDoubleClick(event, item)}
        onDragOver={
          item.kind === "folder"
            ? (event) =>
                handleDropTargetOver(event, `folder:${item.item_id}`, canDropIntoFolder(draggedItem, item.item_id))
            : undefined
        }
        onDragLeave={
          item.kind === "folder"
            ? () => handleDropTargetLeave(`folder:${item.item_id}`)
            : undefined
        }
        onDrop={
          item.kind === "folder"
            ? (event) => {
                if (handleExternalUploadDrop(event, item.item_id, item.name)) {
                  return;
                }
                event.preventDefault();
                void moveDraggedItemTo(item.item_id);
              }
            : undefined
        }
      >
        <div className="drive-tile-main">
          <div className="drive-tile-title">
            <ItemKindBadge kind={item.kind} />
            <strong className="drive-tile-name" title={item.name}>
              {item.name}
            </strong>
          </div>
          {renameItem?.item_id === item.item_id ? (
            <form className="inline-editor drive-tile-editor" onSubmit={handleRenameItem}>
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
                {localActionError?.scope === "rename" && localActionError.itemId === item.item_id ? (
                  <p className="error-text">{localActionError.message}</p>
                ) : null}
              </div>
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
            <form className="inline-editor drive-tile-editor" onSubmit={handleMoveItem}>
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
                {localActionError?.scope === "move" && localActionError.itemId === item.item_id ? (
                  <p className="error-text">{localActionError.message}</p>
                ) : null}
              </div>
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
        <div className="drive-tile-actions">
          <button
            className="row-menu-button"
            type="button"
            aria-label={`More actions for ${item.name}`}
            title={`More actions for ${item.name}`}
            onClick={(event) => handleContextMenuTriggerClick(event, item)}
            disabled={isBusy}
          >
            ⋮
          </button>
        </div>
      </div>
    ));
  }

  function renderContextMenu() {
    if (!contextMenu) {
      return null;
    }

    const { item, x, y } = contextMenu;
    const left = Math.min(x, window.innerWidth - 220);
    const top = Math.min(y, window.innerHeight - 220);

    return (
      <div
        className="context-menu"
        style={{ left, top }}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {item.kind === "folder" ? (
          <button
            className="context-menu-item"
            type="button"
            onClick={() => {
              setContextMenu(null);
              void handleOpenFolder(item);
            }}
          >
            Open
          </button>
        ) : (
          <button
            className="context-menu-item"
            type="button"
            onClick={() => {
              setContextMenu(null);
              void handleDownload(item.item_id, item.name);
            }}
          >
            Download
          </button>
        )}
        <button className="context-menu-item" type="button" onClick={() => showDriveItemDetails(item)}>
          Info
        </button>
        <button className="context-menu-item" type="button" onClick={() => openRenameFromMenu(item)}>
          Rename
        </button>
        <button className="context-menu-item" type="button" onClick={() => openMoveFromMenu(item)}>
          Move to…
        </button>
        <button
          className="context-menu-item context-menu-item-danger"
          type="button"
          onClick={() => {
            setContextMenu(null);
            void handleTrashItem(item);
          }}
        >
          Move to Trash
        </button>
      </div>
    );
  }

  function renderDriveDetailsPanel() {
    if (drivePanelMode === "activity") {
      return (
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
      );
    }

    if (drivePanelMode !== "details" || !selectedDriveItem) {
      return null;
    }

    return (
      <aside className="activity-column">
        <section className="surface side-card">
          <div className="section-header">
            <div>
              <p className="eyebrow">Details</p>
              <h2>{selectedDriveItem.name}</h2>
            </div>
            <button className="secondary-button" type="button" onClick={() => setDrivePanelMode("hidden")}>
              Close
            </button>
          </div>
          <dl className="detail-list">
            <div className="detail-row">
              <dt>Kind</dt>
              <dd>{selectedDriveItem.kind === "folder" ? "Folder" : "File"}</dd>
            </div>
            <div className="detail-row">
              <dt>Path</dt>
              <dd>{buildDriveItemPath(breadcrumbs, selectedDriveItem)}</dd>
            </div>
            {selectedDriveItem.kind === "file" ? (
              <div className="detail-row">
                <dt>Size</dt>
                <dd>{formatBytes(selectedDriveItem.size)}</dd>
              </div>
            ) : null}
            {selectedDriveItem.kind === "file" && selectedDriveItem.mime_type ? (
              <div className="detail-row">
                <dt>Type</dt>
                <dd>{selectedDriveItem.mime_type}</dd>
              </div>
            ) : null}
            <div className="detail-row">
              <dt>Tags</dt>
              <dd>{selectedDriveItem.tags.join(", ") || "No tags"}</dd>
            </div>
            <div className="detail-row">
              <dt>Created</dt>
              <dd>{formatDate(selectedDriveItem.created_at)}</dd>
            </div>
            <div className="detail-row">
              <dt>Updated</dt>
              <dd>{formatDate(selectedDriveItem.updated_at)}</dd>
            </div>
          </dl>
        </section>
      </aside>
    );
  }

  function renderDriveWorkspace() {
    return (
      <div className="app-shell">
        <aside className={sidebarCollapsed ? "sidebar sidebar-collapsed" : "sidebar"}>
          <div className="sidebar-section">
            <button
              className="secondary-button sidebar-toggle"
              type="button"
              onClick={() => setSidebarCollapsed((value) => !value)}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed ? "☰" : "⟨"}
            </button>
          </div>
          <nav className="sidebar-nav" aria-label="Primary">
            <NavButton
              active={currentView === "drive"}
              icon="▣"
              label="My Drive"
              onClick={() => void handleOpenDrive()}
              disabled={isBusy}
              hideLabel={sidebarCollapsed}
            />
            <NavButton
              active={currentView === "trash"}
              icon="⌦"
              label="Trash"
              onClick={() => void handleOpenTrash()}
              disabled={isBusy}
              hideLabel={sidebarCollapsed}
              className={activeDropTarget === "trash" ? "nav-button-drop-target" : ""}
              onDragOver={(event) => handleDropTargetOver(event, "trash", canDropIntoTrash(draggedItem))}
              onDragLeave={() => handleDropTargetLeave("trash")}
              onDrop={(event) => {
                event.preventDefault();
                void trashDraggedItem();
              }}
            />
          </nav>
          {!sidebarCollapsed ? (
            <>
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
                    <span>Files</span>
                    <input
                      id="upload-file"
                      type="file"
                      ref={uploadInputRef}
                      multiple
                      onChange={(event) => {
                        setPendingUploadFiles(Array.from(event.target.files ?? []));
                        setUploadFormError(null);
                      }}
                    />
                  </label>
                  {pendingUploadFiles.length > 0 ? (
                    <p className="muted">
                      {pendingUploadFiles.length} file{pendingUploadFiles.length === 1 ? "" : "s"} selected
                    </p>
                  ) : null}
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
                  <button className="primary-button" type="submit" disabled={pendingUploadFiles.length === 0}>
                    Add to Upload Queue
                  </button>
                </form>
              </section>
            </>
          ) : null}
        </aside>

        <section className="workspace">
          <AppTopBar
            profileLabel={profileLabel}
            searchQuery={searchQuery}
            onSearchQueryChange={(value) => {
              setSearchQuery(value);
              if (searchFormError) {
                setSearchFormError(null);
              }
            }}
            onSearch={handleSearch}
            onLogout={() => void logout()}
            isBusy={isBusy}
            title="Drive"
            secondaryActionLabel="Activity"
            secondaryActionActive={drivePanelMode === "activity"}
            onSecondaryAction={toggleDriveActivityPanel}
          />

          {error ? <div className="error-banner">{error}</div> : null}
          {searchFormError ? <p className="error-text">{searchFormError}</p> : null}

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
                        <button
                          className="primary-button"
                          type="button"
                          onClick={() => {
                            setShowCreateFolderForm((value) => !value);
                            setLocalActionError(null);
                            setError(null);
                          }}
                          disabled={isBusy}
                        >
                          {showCreateFolderForm ? "Close" : "New Folder"}
                        </button>
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
                    {renderUploadQueue()}
                    {breadcrumbs.length > 1 && (
                      <div className="breadcrumbs" aria-label="Breadcrumbs">
                        {breadcrumbs.map((entry, index) => {
                          const isLast = index === breadcrumbs.length - 1;
                        const dropTargetKey: DropTargetKey =
                          entry.folder_id === null ? "breadcrumb:root" : `breadcrumb:${entry.folder_id}`;
                        return (
                          <div
                            className={[
                              "breadcrumb-segment",
                              activeDropTarget === dropTargetKey ? "breadcrumb-drop-target" : "",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                            key={`${entry.folder_id ?? "root"}-${index}`}
                            onDragOver={(event) =>
                              handleDropTargetOver(
                                event,
                                dropTargetKey,
                                canDropIntoParent(draggedItem, entry.folder_id ?? null),
                              )
                            }
                            onDragLeave={() => handleDropTargetLeave(dropTargetKey)}
                            onDrop={(event) => {
                              if (handleExternalUploadDrop(event, entry.folder_id ?? null, entry.name)) {
                                return;
                              }
                              event.preventDefault();
                              void moveDraggedItemTo(entry.folder_id ?? null);
                            }}
                          >
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
                    )}
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
                          {localActionError?.scope === "create-folder" ? (
                            <p className="error-text">{localActionError.message}</p>
                          ) : null}
                        </div>
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
                              setLocalActionError(null);
                              setError(null);
                            }}
                            disabled={isBusy}
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    ) : null}
                    <div
                      className={[
                        "drive-drop-surface",
                        activeDropTarget === "drive-surface" ? "drive-drop-surface-active" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      onDragOver={handleDriveSurfaceDragOver}
                      onDragLeave={handleDriveSurfaceDragLeave}
                      onDrop={handleDriveSurfaceDrop}
                    >
                    <div className="drive-grid">
                      {currentItems.length === 0 ? (
                        <div className="empty-state">
                          <strong>{currentFolderId ? "This folder is empty." : "Your drive is empty."}</strong>
                          <p>{currentFolderId ? "Upload or create a folder here." : "Upload a file or create a folder to get started."}</p>
                        </div>
                      ) : null}
                      {renderDriveRows(currentItems)}
                    </div>
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

            {renderDriveDetailsPanel()}
          </div>
          {renderContextMenu()}
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
            <NavButton
              active={activeAdminSection === "users"}
              icon="◫"
              label="Users"
              onClick={() => scrollToAdminSection("users")}
              disabled={isBusy}
            />
            <NavButton
              active={activeAdminSection === "audit"}
              icon="◪"
              label="Audit"
              onClick={() => scrollToAdminSection("audit")}
              disabled={isBusy}
            />
            <NavButton
              active={activeAdminSection === "errors"}
              icon="⚠"
              label="Errors"
              onClick={() => scrollToAdminSection("errors")}
              disabled={isBusy}
            />
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
          {adminPartialRefreshWarning ? <div className="error-banner">{adminPartialRefreshWarning}</div> : null}

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

              <section className="surface content-surface" ref={adminUsersSectionRef}>
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
                {adminSectionErrors.users ? <div className="notice-card notice-card-warning">{adminSectionErrors.users}</div> : null}
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

              <section className="split-grid" ref={adminAuditSectionRef}>
                <article className="surface content-surface">
                  <div className="section-header">
                    <div>
                      <p className="eyebrow">Audit</p>
                      <h2>Audit Events</h2>
                    </div>
                  </div>
                  {adminSectionErrors.audit ? <div className="notice-card notice-card-warning">{adminSectionErrors.audit}</div> : null}
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
                  {adminSectionErrors.health ? <div className="notice-card notice-card-warning">{adminSectionErrors.health}</div> : null}
                  <div className="table-list">
                    {(adminHealth?.services ?? []).map((service) => (
                      <div className="table-row admin-health-row" key={service.service}>
                        <div className="table-main">
                          <div className="table-title-row">
                            <strong>{service.service}</strong>
                            <span className={service.status === "healthy" ? "status-ok" : "status-bad"}>
                              {service.status}
                            </span>
                          </div>
                          {service.detail ? (
                            <div className="health-detail-block">
                              <p className="muted health-detail-preview">
                                {expandedHealthDetails[service.service]
                                  ? service.detail
                                  : getHealthDetailPreview(service.detail)}
                              </p>
                              <button
                                className="health-detail-toggle"
                                type="button"
                                onClick={() => toggleHealthDetail(service.service)}
                                aria-expanded={expandedHealthDetails[service.service] ? "true" : "false"}
                              >
                                {expandedHealthDetails[service.service] ? "Collapse detail" : "Show detail"}
                              </button>
                            </div>
                          ) : (
                            <p className="muted">No detail</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </article>
              </section>

              <section className="surface content-surface" ref={adminErrorsSectionRef}>
                <div className="section-header">
                  <div>
                    <p className="eyebrow">Operational Errors</p>
                    <h2>Errors / Low-Level Info</h2>
                  </div>
                </div>
                {adminSectionErrors.errors ? <div className="notice-card notice-card-warning">{adminSectionErrors.errors}</div> : null}
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
