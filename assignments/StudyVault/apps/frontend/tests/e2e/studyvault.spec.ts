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
  const activitySurface = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Recent Activity" }) })
    .first();
  const activityRow = activitySurface.locator(".activity-row").filter({ hasText: filename });

  await loginAs(page, "demo", "demo123");

  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(fileContents, "utf-8"),
  });
  await page.getByLabel("Tags").fill(tag);
  await page.getByRole("button", { name: "Upload File" }).click();

  const driveRow = driveSurface.locator(".table-row").filter({ hasText: filename }).first();
  await expect(driveRow).toBeVisible({
    timeout: 60_000,
  });

  await page.getByPlaceholder("Search files and folders").fill(tag);
  await page.getByRole("button", { name: "Search" }).click();
  const searchSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "Search Results" }) }).first();
  const searchRow = searchSurface.locator(".table-row").filter({ hasText: filename }).first();
  await expect(searchRow).toBeVisible();
  await expect(searchRow).toContainText(tag);

  await expect(activityRow.getByText("file_uploaded")).toBeVisible();
  await expect(activityRow.getByText(filename)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await driveRow.getByRole("button", { name: "Download" }).click();
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

test("admin login shows admin indicator", async ({ page }) => {
  await loginAs(page, "admin", "admin123");

  await expect(page.getByText("Admin Console")).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: "Users" }) }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Events" })).toBeVisible();
});
