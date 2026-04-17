import { expect, test, type Page } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080";
const ELASTICSEARCH_URL = process.env.ELASTICSEARCH_URL ?? "http://localhost:9200";

async function loginAs(page: Page, username: string, password: string) {
  await page.goto(BASE_URL);
  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create Account" })).toBeVisible();
  await page.getByRole("button", { name: "Log In With Keycloak" }).click();
  await expect(page).toHaveURL(/\/realms\/studyvault\//);
  await expect(page.locator("#username")).toBeVisible();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
}

test("login, upload, search, activity, download, and log ingestion", async ({ page, request }) => {
  const uniqueId = Date.now().toString();
  const filename = `notes-${uniqueId}.txt`;
  const fileContents = `StudyVault runtime smoke ${uniqueId}`;
  const tag = `tag-${uniqueId}`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await loginAs(page, "demo", "demo123");

  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Search Results" })).toHaveCount(0);

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(fileContents, "utf-8"),
  });
  await page.getByLabel("Tags").fill(tag);
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const driveTile = driveSurface.locator(".drive-tile").filter({ hasText: filename }).first();
  await expect(driveTile).toBeVisible({
    timeout: 60_000,
  });

  await page.getByPlaceholder("Search files and folders").fill(tag);
  await page.getByRole("button", { name: "Search" }).click();
  const searchSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "Search Results" }) }).first();
  const searchRow = searchSurface.locator(".table-row").filter({ hasText: filename }).first();
  await expect(searchRow).toBeVisible();
  await expect(searchRow).toContainText(tag);
  await searchSurface.getByRole("button", { name: "Close Search" }).click();
  await expect(page.getByRole("heading", { name: "Search Results" })).toHaveCount(0);

  await page.getByRole("button", { name: "Activity" }).click();
  const activitySurface = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Recent Activity" }) })
    .first();
  const activityRow = activitySurface.locator(".activity-row").filter({ hasText: filename });
  await expect(activityRow.getByText("file_uploaded")).toBeVisible();
  await expect(activityRow.getByText(filename)).toBeVisible();

  const contextMenu = page.locator(".context-menu");
  await driveSurface.getByRole("button", { name: `More actions for ${filename}` }).click();
  await expect(contextMenu).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await contextMenu.getByRole("button", { name: "Download" }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) {
    chunks.push(Buffer.from(chunk));
  }
  expect(Buffer.concat(chunks).toString("utf-8")).toContain(fileContents);

  await expect
    .poll(
      async () => {
        const response = await request.get(`${ELASTICSEARCH_URL}/studyvault-logs-*/_search`, {
          params: {
            q: `service:file-service AND event_name:file_upload_succeeded AND filename:"${filename}"`,
            size: "1",
            sort: "@timestamp:desc",
          },
        });
        if (!response.ok()) {
          return 0;
        }
        const payload = await response.json();
        return payload.hits?.hits?.length ?? 0;
      },
      { timeout: 60_000, intervals: [1000, 2000, 5000] },
    )
    .toBeGreaterThan(0);
});

test("file can be dragged into a folder tile", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `folder-${uniqueId}`;
  const filename = `drag-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`drag test ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const fileRow = driveSurface.locator(".drive-tile").filter({ hasText: filename }).first();
  const folderRow = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();

  await expect(fileRow).toBeVisible({ timeout: 60_000 });
  await expect(folderRow).toBeVisible({ timeout: 60_000 });

  await fileRow.dragTo(folderRow);

  await expect(driveSurface.locator(".drive-tile").filter({ hasText: filename })).toHaveCount(0);
});

test("single click selects a folder and double click navigates into it", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `single-click-${uniqueId}`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const folderRow = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();
  await expect(folderRow).toBeVisible({ timeout: 60_000 });

  await folderRow.click();

  const detailsPanel = page.locator("aside").filter({ has: page.getByRole("heading", { name: folderName }) }).first();
  await expect(detailsPanel).toBeVisible();
  await expect(page.locator(".breadcrumb-current")).not.toContainText(folderName);

  await folderRow.dblclick();

  await expect(page.locator(".breadcrumb-current")).toContainText(folderName);
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: folderName }) }).first()).toBeVisible();
});

test("new folder action moved into drive header and sidebar can collapse", async ({ page }) => {
  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const sidebar = page.locator("aside.sidebar").first();

  await expect(page.getByRole("button", { name: /^New$/ })).toHaveCount(0);
  await expect(driveSurface.getByRole("button", { name: "New Folder" })).toBeVisible();

  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(sidebar).toHaveClass(/sidebar-collapsed/);
  await expect(sidebar.getByText("Current Location")).toHaveCount(0);
  await expect(sidebar.getByRole("button", { name: "My Drive" })).toBeVisible();
  await expect(sidebar.getByRole("button", { name: "Trash" })).toBeVisible();

  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(sidebar).not.toHaveClass(/sidebar-collapsed/);
  await expect(sidebar.getByText("Current Location")).toBeVisible();
});

test("context menu info opens details and selection overrides activity panel", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `info-${uniqueId}.txt`;
  const tag = `info-tag-${uniqueId}`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`info test ${uniqueId}`, "utf-8"),
  });
  await page.getByLabel("Tags").fill(tag);
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const fileRow = driveSurface.locator(".drive-tile").filter({ hasText: filename }).first();
  await expect(fileRow).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Activity" }).click();
  await expect(page.getByRole("heading", { name: "Recent Activity" })).toBeVisible();

  await fileRow.getByRole("button", { name: `More actions for ${filename}` }).click();
  await page.locator(".context-menu").getByRole("button", { name: "Info" }).click();

  const detailsPanel = page.locator("aside").filter({ has: page.getByRole("heading", { name: filename }) }).first();
  await expect(detailsPanel).toBeVisible();
  await expect(detailsPanel).toContainText(tag);
  await expect(page.getByRole("heading", { name: "Recent Activity" })).toHaveCount(0);
});

test("long file names expose full value in grid tooltip and details panel", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `very-long-studyvault-file-name-${uniqueId}-with-extra-description-to-test-hover-expansion-and-tooltips.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`long name ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const fileTile = driveSurface.locator(".drive-tile").filter({ has: page.locator(`.drive-tile-name[title="${filename}"]`) }).first();
  await expect(fileTile).toBeVisible({ timeout: 60_000 });

  const tileName = fileTile.locator(".drive-tile-name");
  await expect(tileName).toHaveAttribute("title", filename);
  await fileTile.click();

  const detailsPanel = page.locator("aside").filter({ has: page.getByRole("heading", { name: filename }) }).first();
  await expect(detailsPanel).toBeVisible();
});

test("refresh keeps the existing authenticated session", async ({ page }) => {
  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });

  await page.reload();

  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toHaveCount(0);
});

test("admin login shows admin indicator", async ({ page }) => {
  await loginAs(page, "admin", "admin123");

  await expect(page.getByText("Admin Console")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: "Users" }) }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Events" })).toBeVisible();

  const usersNav = page.getByRole("button", { name: "Users" }).first();
  const auditNav = page.getByRole("button", { name: "Audit" }).first();
  const errorsNav = page.getByRole("button", { name: "Errors" }).first();

  await expect(usersNav).toHaveAttribute("aria-pressed", "true");
  await auditNav.click();
  await expect(auditNav).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Audit Events" })).toBeInViewport();

  await errorsNav.click();
  await expect(errorsNav).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Errors / Low-Level Info" })).toBeInViewport();

  const systemHealth = page.locator("article").filter({ has: page.getByRole("heading", { name: "System Health" }) });
  const detailToggle = systemHealth.getByRole("button", { name: "Show detail" }).first();
  await expect(detailToggle).toHaveAttribute("aria-expanded", "false");
  await detailToggle.click();
  await expect(detailToggle).toHaveAttribute("aria-expanded", "true");
});

test("multiple files can be queued from the picker and complete in the shared upload queue", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const firstFilename = `queue-a-${uniqueId}.txt`;
  const secondFilename = `queue-b-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.locator("#upload-file").setInputFiles([
    {
      name: firstFilename,
      mimeType: "text/plain",
      buffer: Buffer.from(`queue first ${uniqueId}`, "utf-8"),
    },
    {
      name: secondFilename,
      mimeType: "text/plain",
      buffer: Buffer.from(`queue second ${uniqueId}`, "utf-8"),
    },
  ]);
  await page.getByLabel("Tags").fill(`queue-tag-${uniqueId}`);
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  await expect(queuePanel).toBeVisible();
  await expect(queuePanel).toContainText(firstFilename);
  await expect(queuePanel).toContainText(secondFilename);

  await expect(driveSurface.locator(".drive-tile").filter({ hasText: firstFilename }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(driveSurface.locator(".drive-tile").filter({ hasText: secondFilename }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(queuePanel.locator(".upload-status-done")).toHaveCount(2, { timeout: 60_000 });
});

test("failed queued uploads stay visible with retry and dismiss actions", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `retry-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();
  let failNextUpload = true;

  await page.route("**/api/files", async (route, request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/files" && failNextUpload) {
      failNextUpload = false;
      await route.fulfill({
        status: 500,
        contentType: "text/plain",
        body: "forced upload failure",
      });
      return;
    }
    await route.fallback();
  });

  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`retry upload ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const queueRow = queuePanel.locator(".upload-queue-row").filter({ hasText: filename }).first();
  await expect(queueRow).toBeVisible({ timeout: 60_000 });
  await expect(queueRow).toContainText("forced upload failure");
  await expect(queueRow.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(queueRow.getByRole("button", { name: "Dismiss" })).toBeVisible();

  await queueRow.getByRole("button", { name: "Retry" }).click();

  await expect(driveSurface.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(queueRow).toContainText("done");
});
