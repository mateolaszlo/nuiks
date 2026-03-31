import { expect, test } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080";
const ELASTICSEARCH_URL = process.env.ELASTICSEARCH_URL ?? "http://localhost:9200";

test("login, upload, search, activity, download, and log ingestion", async ({ page, request }) => {
  const uniqueId = Date.now().toString();
  const filename = `notes-${uniqueId}.txt`;
  const fileContents = `StudyVault runtime smoke ${uniqueId}`;
  const tag = `tag-${uniqueId}`;
  const myFilesPanel = page.locator("article").filter({ has: page.getByRole("heading", { name: "My Files" }) });
  const searchPanel = page.locator("article").filter({ has: page.getByRole("heading", { name: "Search" }) });
  const activityPanel = page
    .locator("article")
    .filter({ has: page.getByRole("heading", { name: "Recent Activity" }) });
  const activityRow = activityPanel.locator(".result-card").filter({ hasText: filename });

  await page.goto(BASE_URL);
  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toBeVisible();
  await page.getByRole("button", { name: "Log In With Keycloak" }).click();
  await expect(page).toHaveURL(/\/realms\/studyvault\//);
  await expect(page.locator("#username")).toBeVisible();

  await page.locator("#username").fill("demo");
  await page.locator("#password").fill("demo123");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByRole("heading", { name: "demo" })).toBeVisible({ timeout: 60_000 });

  await page.getByLabel("File").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(fileContents, "utf-8"),
  });
  await page.getByLabel("Tags").fill(tag);
  await page.getByRole("button", { name: "Upload File" }).click();

  await expect(myFilesPanel.getByText(filename)).toBeVisible({ timeout: 60_000 });

  await page.getByPlaceholder("Search by filename or tag").fill(tag);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(searchPanel.getByText(filename)).toBeVisible();
  await expect(searchPanel.getByText(tag)).toBeVisible();

  await expect(activityRow.getByText("file_uploaded")).toBeVisible();
  await expect(activityRow.getByText(filename)).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await myFilesPanel.getByRole("button", { name: "Download" }).first().click();
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
        const response = await request.get(
          `${ELASTICSEARCH_URL}/studyvault-logs-*/_search?q=service:file-service AND message:\"POST /api/files\"&size=5`,
        );
        if (!response.ok()) {
          return "";
        }
        return await response.text();
      },
      { timeout: 60_000, intervals: [1000, 2000, 5000] },
    )
    .toContain("POST /api/files");
});
