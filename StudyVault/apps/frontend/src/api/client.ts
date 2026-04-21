import type {
  ActivityRecord,
  AdminAuditEvent,
  AdminErrorRecord,
  CatalogBreadcrumbsResponse,
  ApiErrorResponse,
  AdminHealthSummary,
  AdminPasswordResetResult,
  CatalogRestoreResponse,
  CatalogTrashResponse,
  AdminUserSummary,
  CatalogItemsResponse,
  DriveItem,
  FileRecord,
  FileRestoreResponse,
  FolderRecord,
} from "./types";

type UploadProgressOptions = {
  onProgress?: (percent: number) => void;
  onProcessing?: () => void;
};

export class ApiError extends Error {
  status: number;
  code: string;
  category: ApiErrorResponse["category"];
  recoverable: boolean;
  context: Record<string, string | number | boolean | null>;
  fieldErrors: ApiErrorResponse["field_errors"];

  constructor(
    message: string,
    options: {
      status: number;
      code: string;
      category: ApiErrorResponse["category"];
      recoverable?: boolean;
      context?: Record<string, string | number | boolean | null> | null;
      fieldErrors?: ApiErrorResponse["field_errors"];
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.category = options.category;
    this.recoverable = options.recoverable ?? options.status < 500;
    this.context = options.context ?? {};
    this.fieldErrors = options.fieldErrors ?? [];
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function isAuthApiError(error: unknown): error is ApiError {
  return isApiError(error) && error.category === "auth";
}

export function isPermissionApiError(error: unknown): error is ApiError {
  return isApiError(error) && error.category === "permission";
}

export class ApiClient {
  constructor(private readonly getToken: () => Promise<string | undefined>) {}

  private async request<T>(input: string, init?: RequestInit): Promise<T> {
    const token = await this.getToken();
    const headers = new Headers(init?.headers ?? {});
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(input, { ...init, headers });
    if (!response.ok) {
      throw await readApiErrorFromResponse(response);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  listFiles(): Promise<FileRecord[]> {
    return this.request<FileRecord[]>("/api/v1/catalog/files");
  }

  listCatalogItems(parentFolderId?: string | null): Promise<CatalogItemsResponse> {
    const query = parentFolderId ? `?parent_id=${encodeURIComponent(parentFolderId)}` : "";
    return this.request<CatalogItemsResponse>(`/api/v1/catalog/items${query}`);
  }

  getBreadcrumbs(folderId: string): Promise<CatalogBreadcrumbsResponse> {
    return this.request<CatalogBreadcrumbsResponse>(
      `/api/v1/catalog/breadcrumbs/${encodeURIComponent(folderId)}`,
    );
  }

  listTrash(): Promise<CatalogTrashResponse> {
    return this.request<CatalogTrashResponse>("/api/v1/catalog/trash");
  }

  createFolder(name: string, parentFolderId?: string | null): Promise<FolderRecord> {
    return this.request<FolderRecord>("/api/v1/catalog/folders", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name,
        parent_folder_id: parentFolderId ?? null,
      }),
    });
  }

  renameFile(fileId: string, name: string): Promise<FileRecord> {
    return this.request<FileRecord>(`/api/v1/files/${encodeURIComponent(fileId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  renameFolder(folderId: string, name: string): Promise<FolderRecord> {
    return this.request<FolderRecord>(`/api/v1/catalog/folders/${encodeURIComponent(folderId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  moveFile(fileId: string, parentFolderId?: string | null): Promise<FileRecord> {
    return this.request<FileRecord>(`/api/v1/files/${encodeURIComponent(fileId)}/move`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  moveFolder(folderId: string, parentFolderId?: string | null): Promise<FolderRecord> {
    return this.request<FolderRecord>(`/api/v1/catalog/folders/${encodeURIComponent(folderId)}/move`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  trashFile(fileId: string): Promise<void> {
    return this.request<void>(`/api/v1/files/${encodeURIComponent(fileId)}`, {
      method: "DELETE",
    });
  }

  restoreFile(fileId: string, parentFolderId?: string | null): Promise<FileRestoreResponse> {
    return this.request<FileRestoreResponse>(`/api/v1/files/${encodeURIComponent(fileId)}/restore`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  trashFolder(folderId: string): Promise<void> {
    return this.request<void>(`/api/v1/catalog/folders/${encodeURIComponent(folderId)}`, {
      method: "DELETE",
    });
  }

  restoreFolder(folderId: string, parentFolderId?: string | null): Promise<CatalogRestoreResponse> {
    return this.request<CatalogRestoreResponse>(
      `/api/v1/catalog/folders/${encodeURIComponent(folderId)}/restore`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
      },
    );
  }

  search(
    query: string,
    options?: { kind?: "file" | "folder" | "all"; includeTrashed?: boolean; parentId?: string | null },
  ): Promise<DriveItem[]> {
    const params = new URLSearchParams({ q: query });
    if (options?.kind) {
      params.set("kind", options.kind);
    }
    if (options?.includeTrashed) {
      params.set("include_trashed", "true");
    }
    if (options?.parentId) {
      params.set("parent_id", options.parentId);
    }
    return this.request<DriveItem[]>(`/api/v1/search?${params.toString()}`);
  }

  listActivity(): Promise<ActivityRecord[]> {
    return this.request<ActivityRecord[]>("/api/v1/activity/me");
  }

  uploadFile(file: File, tags: string[], parentFolderId?: string | null): Promise<FileRecord> {
    return this.uploadFileWithProgress(file, tags, parentFolderId);
  }

  async uploadFileWithProgress(
    file: File,
    tags: string[],
    parentFolderId?: string | null,
    options?: UploadProgressOptions,
  ): Promise<FileRecord> {
    const body = new FormData();
    body.append("file", file);
    for (const tag of tags) {
      body.append("tags", tag);
    }
    if (parentFolderId) {
      body.append("parent_folder_id", parentFolderId);
    }
    const token = await this.getToken();

    return await new Promise<FileRecord>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      let processingNotified = false;
      xhr.open("POST", "/api/v1/files");
      xhr.responseType = "text";
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }

      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) {
          return;
        }
        const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
        options?.onProgress?.(percent);
      };

      xhr.upload.onload = () => {
        options?.onProgress?.(100);
      };

      const notifyProcessing = () => {
        if (processingNotified) {
          return;
        }
        processingNotified = true;
        options?.onProcessing?.();
      };

      xhr.onreadystatechange = () => {
        if (
          xhr.readyState >= XMLHttpRequest.HEADERS_RECEIVED &&
          xhr.readyState < XMLHttpRequest.DONE
        ) {
          notifyProcessing();
        }
      };

      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.onabort = () => reject(new Error("Upload was aborted"));
      xhr.onload = () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(readApiErrorFromText(xhr.responseText, xhr.status));
          return;
        }

        try {
          notifyProcessing();
          resolve(JSON.parse(xhr.responseText) as FileRecord);
        } catch (parseError) {
          reject(parseError instanceof Error ? parseError : new Error("Upload response parsing failed"));
        }
      };

      xhr.send(body);
    });
  }

  async downloadFile(fileId: string): Promise<Blob> {
    const token = await this.getToken();
    const headers = new Headers();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`/api/v1/files/${fileId}/download`, { headers });
    if (!response.ok) {
      throw await readApiErrorFromResponse(response);
    }
    return await response.blob();
  }

  listAdminUsers(): Promise<AdminUserSummary[]> {
    return this.request<AdminUserSummary[]>("/api/v1/admin/users");
  }

  disableUser(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/v1/admin/users/${userId}/disable`, { method: "POST" });
  }

  enableUser(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/v1/admin/users/${userId}/enable`, { method: "POST" });
  }

  grantAdmin(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/v1/admin/users/${userId}/grant-admin`, { method: "POST" });
  }

  revokeAdmin(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/v1/admin/users/${userId}/revoke-admin`, { method: "POST" });
  }

  resetPassword(userId: string): Promise<AdminPasswordResetResult> {
    return this.request<AdminPasswordResetResult>(`/api/v1/admin/users/${userId}/reset-password`, {
      method: "POST",
    });
  }

  listAdminAudit(limit = 100): Promise<AdminAuditEvent[]> {
    return this.request<AdminAuditEvent[]>(`/api/v1/admin/audit?limit=${limit}`);
  }

  getAdminHealth(): Promise<AdminHealthSummary> {
    return this.request<AdminHealthSummary>("/api/v1/admin/health");
  }

  listAdminErrors(limit = 50): Promise<AdminErrorRecord[]> {
    return this.request<AdminErrorRecord[]>(`/api/v1/admin/errors?limit=${limit}`);
  }
}

async function readApiErrorFromResponse(response: Response): Promise<ApiError> {
  const responseText = await response.text();
  return readApiErrorFromText(responseText, response.status);
}

function readApiErrorFromText(responseText: string, status: number): ApiError {
  if (!responseText) {
    return new ApiError(`Request failed with status ${status}`, {
      status,
      code: defaultErrorCode(status),
      category: defaultErrorCategory(status),
    });
  }

  try {
    const payload = JSON.parse(responseText) as Partial<ApiErrorResponse>;
    if (typeof payload.detail === "string" && typeof payload.code === "string" && typeof payload.category === "string") {
      return new ApiError(payload.detail, {
        status,
        code: payload.code,
        category: payload.category,
        recoverable: payload.recoverable,
        context: payload.context,
        fieldErrors: payload.field_errors,
      });
    }
    if (typeof payload.detail === "string") {
      return new ApiError(payload.detail, {
        status,
        code: defaultErrorCode(status),
        category: defaultErrorCategory(status),
      });
    }
  } catch {
    // Fall through to raw-text fallback.
  }

  return new ApiError(responseText || `Request failed with status ${status}`, {
    status,
    code: defaultErrorCode(status),
    category: defaultErrorCategory(status),
  });
}

function defaultErrorCategory(status: number): ApiErrorResponse["category"] {
  if (status === 404) {
    return "not_found";
  }
  if (status === 401) {
    return "auth";
  }
  if (status === 403) {
    return "permission";
  }
  if (status === 409) {
    return "conflict";
  }
  if (status === 400 || status === 422) {
    return "validation";
  }
  if (status >= 500) {
    return "unavailable";
  }
  return "internal";
}

function defaultErrorCode(status: number): string {
  if (status === 404) {
    return "not_found";
  }
  if (status === 401) {
    return "unauthorized";
  }
  if (status === 403) {
    return "forbidden";
  }
  if (status === 409) {
    return "conflict";
  }
  if (status === 400 || status === 422) {
    return "invalid_request";
  }
  if (status >= 500) {
    return "service_unavailable";
  }
  return "internal_error";
}
