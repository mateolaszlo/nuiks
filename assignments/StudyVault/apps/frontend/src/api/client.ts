import type {
  ActivityRecord,
  AdminAuditEvent,
  AdminErrorRecord,
  CatalogBreadcrumbsResponse,
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
      const detail = await response.text();
      throw new Error(detail || `Request failed with status ${response.status}`);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  listFiles(): Promise<FileRecord[]> {
    return this.request<FileRecord[]>("/api/catalog/files");
  }

  listCatalogItems(parentFolderId?: string | null): Promise<CatalogItemsResponse> {
    const query = parentFolderId ? `?parent_id=${encodeURIComponent(parentFolderId)}` : "";
    return this.request<CatalogItemsResponse>(`/api/catalog/items${query}`);
  }

  getBreadcrumbs(folderId: string): Promise<CatalogBreadcrumbsResponse> {
    return this.request<CatalogBreadcrumbsResponse>(
      `/api/catalog/breadcrumbs/${encodeURIComponent(folderId)}`,
    );
  }

  listTrash(): Promise<CatalogTrashResponse> {
    return this.request<CatalogTrashResponse>("/api/catalog/trash");
  }

  createFolder(name: string, parentFolderId?: string | null): Promise<FolderRecord> {
    return this.request<FolderRecord>("/api/catalog/folders", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name,
        parent_folder_id: parentFolderId ?? null,
      }),
    });
  }

  renameFile(fileId: string, name: string): Promise<FileRecord> {
    return this.request<FileRecord>(`/api/files/${encodeURIComponent(fileId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  renameFolder(folderId: string, name: string): Promise<FolderRecord> {
    return this.request<FolderRecord>(`/api/catalog/folders/${encodeURIComponent(folderId)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  moveFile(fileId: string, parentFolderId?: string | null): Promise<FileRecord> {
    return this.request<FileRecord>(`/api/files/${encodeURIComponent(fileId)}/move`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  moveFolder(folderId: string, parentFolderId?: string | null): Promise<FolderRecord> {
    return this.request<FolderRecord>(`/api/catalog/folders/${encodeURIComponent(folderId)}/move`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  trashFile(fileId: string): Promise<void> {
    return this.request<void>(`/api/files/${encodeURIComponent(fileId)}`, {
      method: "DELETE",
    });
  }

  restoreFile(fileId: string, parentFolderId?: string | null): Promise<FileRestoreResponse> {
    return this.request<FileRestoreResponse>(`/api/files/${encodeURIComponent(fileId)}/restore`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ parent_folder_id: parentFolderId ?? null }),
    });
  }

  trashFolder(folderId: string): Promise<void> {
    return this.request<void>(`/api/catalog/folders/${encodeURIComponent(folderId)}`, {
      method: "DELETE",
    });
  }

  restoreFolder(folderId: string, parentFolderId?: string | null): Promise<CatalogRestoreResponse> {
    return this.request<CatalogRestoreResponse>(
      `/api/catalog/folders/${encodeURIComponent(folderId)}/restore`,
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
    return this.request<DriveItem[]>(`/api/search?${params.toString()}`);
  }

  listActivity(): Promise<ActivityRecord[]> {
    return this.request<ActivityRecord[]>("/api/activity/me");
  }

  uploadFile(file: File, tags: string[], parentFolderId?: string | null): Promise<FileRecord> {
    const body = new FormData();
    body.append("file", file);
    for (const tag of tags) {
      body.append("tags", tag);
    }
    if (parentFolderId) {
      body.append("parent_folder_id", parentFolderId);
    }

    return this.request<FileRecord>("/api/files", {
      method: "POST",
      body,
    });
  }

  async downloadFile(fileId: string): Promise<Blob> {
    const token = await this.getToken();
    const headers = new Headers();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(`/api/files/${fileId}/download`, { headers });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `Request failed with status ${response.status}`);
    }
    return await response.blob();
  }

  listAdminUsers(): Promise<AdminUserSummary[]> {
    return this.request<AdminUserSummary[]>("/api/admin/users");
  }

  disableUser(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/admin/users/${userId}/disable`, { method: "POST" });
  }

  enableUser(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/admin/users/${userId}/enable`, { method: "POST" });
  }

  grantAdmin(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/admin/users/${userId}/grant-admin`, { method: "POST" });
  }

  revokeAdmin(userId: string): Promise<AdminUserSummary> {
    return this.request<AdminUserSummary>(`/api/admin/users/${userId}/revoke-admin`, { method: "POST" });
  }

  resetPassword(userId: string): Promise<AdminPasswordResetResult> {
    return this.request<AdminPasswordResetResult>(`/api/admin/users/${userId}/reset-password`, {
      method: "POST",
    });
  }

  listAdminAudit(limit = 100): Promise<AdminAuditEvent[]> {
    return this.request<AdminAuditEvent[]>(`/api/admin/audit?limit=${limit}`);
  }

  getAdminHealth(): Promise<AdminHealthSummary> {
    return this.request<AdminHealthSummary>("/api/admin/health");
  }

  listAdminErrors(limit = 50): Promise<AdminErrorRecord[]> {
    return this.request<AdminErrorRecord[]>(`/api/admin/errors?limit=${limit}`);
  }
}
