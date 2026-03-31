import { FormEvent, startTransition, useEffect, useMemo, useState } from "react";

import { ApiClient } from "./api/client";
import type { ActivityRecord, FileRecord } from "./api/types";
import {
  getAccessToken,
  getProfileSummary,
  initializeAuth,
  isAuthenticated,
  login,
  logout,
} from "./auth/keycloak";

type LoadState = "loading" | "ready" | "error";

function formatDate(value: string): string {
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
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [searchResults, setSearchResults] = useState<FileRecord[]>([]);
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  async function refreshDashboard() {
    const [filePayload, activityPayload] = await Promise.all([
      api.listFiles(),
      api.listActivity(),
    ]);
    startTransition(() => {
      setFiles(filePayload);
      setSearchResults(filePayload);
      setActivities(activityPayload);
    });
  }

  useEffect(() => {
    async function bootstrap() {
      try {
        const loggedIn = await initializeAuth();
        const authReady = loggedIn || isAuthenticated();
        setAuthenticated(authReady);
        setProfileLabel(getProfileSummary());
        setAuthState("ready");
        setError(null);
        if (authReady) {
          try {
            await refreshDashboard();
          } catch (dashboardError) {
            setError(
              dashboardError instanceof Error
                ? dashboardError.message
                : String(dashboardError),
            );
          }
        }
      } catch (bootstrapError) {
        setAuthState("error");
        setError(
          bootstrapError instanceof Error
            ? bootstrapError.message
            : String(bootstrapError),
        );
      }
    }

    void bootstrap();
  }, []);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setSearchResults(files);
      return;
    }

    try {
      setIsBusy(true);
      const payload = await api.search(searchQuery.trim());
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
      await api.uploadFile(selectedFile, tags);
      setSelectedFile(null);
      setTagInput("");
      await refreshDashboard();
      setError(null);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed");
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

  if (authState === "loading") {
    return <main className="shell"><section className="hero-card">Loading StudyVault…</section></main>;
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
          <p className="eyebrow">Microservice MVP</p>
          <h1>StudyVault</h1>
          <p>
            Sign in to upload study materials, review your file catalog, search metadata,
            and inspect recent activity.
          </p>
          <button className="primary-button" onClick={() => void login()}>
            Log In With Keycloak
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Signed in</p>
          <h1>{profileLabel}</h1>
          <p>Upload files, search by tag or filename, and verify the MVP flow end to end.</p>
        </div>
        <button className="secondary-button" onClick={() => void logout()}>
          Log Out
        </button>
      </section>

      <section className="grid">
        <article className="panel">
          <h2>Upload</h2>
          <form className="stack" onSubmit={handleUpload}>
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
              placeholder="Search by filename or tag"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
            <button className="secondary-button" type="submit" disabled={isBusy}>
              Search
            </button>
          </form>
          <div className="results">
            {searchResults.length === 0 ? <p className="muted">No matching files yet.</p> : null}
            {searchResults.map((file) => (
              <div className="result-card" key={file.file_id}>
                <div>
                  <strong>{file.filename}</strong>
                  <p>{file.tags.join(", ") || "No tags"}</p>
                </div>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => void handleDownload(file.file_id, file.filename)}
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid">
        <article className="panel">
          <h2>My Files</h2>
          <div className="results">
            {files.length === 0 ? <p className="muted">Upload your first study file to populate the catalog.</p> : null}
            {files.map((file) => (
              <div className="result-card" key={file.file_id}>
                <div>
                  <strong>{file.filename}</strong>
                  <p>{file.mime_type} • {file.size} bytes</p>
                  <p>{formatDate(file.created_at)}</p>
                </div>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => void handleDownload(file.file_id, file.filename)}
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <h2>Recent Activity</h2>
          <div className="results">
            {activities.length === 0 ? <p className="muted">Activity will appear after the first upload.</p> : null}
            {activities.map((activity) => (
              <div className="result-card" key={activity.activity_id}>
                <div>
                  <strong>{activity.action}</strong>
                  <p>{activity.filename}</p>
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
