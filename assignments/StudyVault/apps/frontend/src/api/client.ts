import type { ActivityRecord, FileRecord } from "./types";

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

  search(query: string): Promise<FileRecord[]> {
    return this.request<FileRecord[]>(`/api/search?q=${encodeURIComponent(query)}`);
  }

  listActivity(): Promise<ActivityRecord[]> {
    return this.request<ActivityRecord[]>("/api/activity/me");
  }

  uploadFile(file: File, tags: string[]): Promise<FileRecord> {
    const body = new FormData();
    body.append("file", file);
    for (const tag of tags) {
      body.append("tags", tag);
    }

    return this.request<FileRecord>("/api/files", {
      method: "POST",
      body,
    });
  }
}
