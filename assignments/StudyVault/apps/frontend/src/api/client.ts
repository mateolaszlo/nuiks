import type {
  ActivityRecord,
  AdminAuditEvent,
  AdminErrorRecord,
  AdminHealthSummary,
  AdminPasswordResetResult,
  AdminUserSummary,
  CatalogItemsResponse,
  FileRecord,
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
    return (await response.json()) as T;
  }

  listFiles(): Promise<FileRecord[]> {
    return this.request<FileRecord[]>("/api/catalog/files");
  }

  listCatalogItems(parentFolderId?: string | null): Promise<CatalogItemsResponse> {
    const query = parentFolderId ? `?parent_id=${encodeURIComponent(parentFolderId)}` : "";
    return this.request<CatalogItemsResponse>(`/api/catalog/items${query}`);
  }

  search(query: string): Promise<FileRecord[]> {
    return this.request<FileRecord[]>(`/api/search?q=${encodeURIComponent(query)}`);
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
