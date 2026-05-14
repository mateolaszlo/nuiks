import { expect, test } from "@playwright/test";

import {
  ADMIN_STORAGE_STATE,
  BASE_URL,
  DEMO_STORAGE_STATE,
  ELASTICSEARCH_URL,
  loginAs,
  openAdminWorkspace,
  openDriveWorkspace,
} from "./helpers";

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

test.describe("authenticated drive workspace", () => {
  test.use({ storageState: DEMO_STORAGE_STATE });

test("profile menu shows token details and account links", async ({ page }) => {
  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "Open profile menu for demo" }).click();
  const profileMenu = page.getByRole("menu", { name: "Profile Menu" });

  await expect(profileMenu).toBeVisible();
  await expect(profileMenu).toContainText("demo");
  await expect(profileMenu).toContainText("demo@studyvault.local");
  await expect(profileMenu.getByRole("menuitem", { name: "Manage Account" })).toHaveAttribute(
    "href",
    new RegExp(`^${BASE_URL}/realms/studyvault/account\\?referrer=studyvault-frontend&referrer_uri=${encodeURIComponent(BASE_URL)}$`),
  );
  await expect(profileMenu.getByRole("menuitem", { name: "Change Password" })).toHaveAttribute(
    "href",
    new RegExp(`^${BASE_URL}/realms/studyvault/account\\?referrer=studyvault-frontend&referrer_uri=${encodeURIComponent(BASE_URL)}#/security/signingin$`),
  );

  await page.getByRole("heading", { name: "My Drive" }).click();
  await expect(profileMenu).toHaveCount(0);
});

test("file can be dragged into a folder tile", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `folder-${uniqueId}`;
  const filename = `drag-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await openDriveWorkspace(page);

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

test("external files can be dropped onto the current drive surface and enter the upload queue", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `drop-target-${uniqueId}`;
  const filename = `external-drop-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const folderTile = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();
  await expect(folderTile).toBeVisible({ timeout: 60_000 });
  await folderTile.dblclick();

  await expect(page.locator(".breadcrumb-current")).toContainText(folderName);

  const dropSurface = page.locator(".drive-drop-surface").first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();
  await dropSurface.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File([payload.fileContents], payload.dropFilename, { type: "text/plain" }));
      node.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer }));
    },
    { dropFilename: filename, fileContents: `external drop ${uniqueId}` },
  );
  await expect(dropSurface).toHaveClass(/drive-drop-surface-active/);
  await dropSurface.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File([payload.fileContents], payload.dropFilename, { type: "text/plain" }));
      node.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
    },
    { dropFilename: filename, fileContents: `external drop ${uniqueId}` },
  );

  await expect(queuePanel).toBeVisible();
  await expect(queuePanel).toContainText(filename);
  await expect(page.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });
});

test("external files can be dropped onto a folder tile and upload into that folder", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `folder-drop-${uniqueId}`;
  const filenames = [`tile-drop-a-${uniqueId}.txt`, `tile-drop-b-${uniqueId}.txt`];
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const folderTile = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await expect(folderTile).toBeVisible({ timeout: 60_000 });
  await folderTile.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      for (const file of payload.files) {
        dataTransfer.items.add(new File([file.contents], file.name, { type: "text/plain" }));
      }
      node.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer }));
    },
    {
      files: filenames.map((name, index) => ({
        name,
        contents: `folder tile drop ${uniqueId}-${index}`,
      })),
    },
  );
  await folderTile.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      for (const file of payload.files) {
        dataTransfer.items.add(new File([file.contents], file.name, { type: "text/plain" }));
      }
      node.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
    },
    {
      files: filenames.map((name, index) => ({
        name,
        contents: `folder tile drop ${uniqueId}-${index}`,
      })),
    },
  );

  await expect(queuePanel).toBeVisible();
  for (const filename of filenames) {
    await expect(queuePanel).toContainText(filename);
  }
  await expect(queuePanel).toContainText(`Destination: ${folderName}`);
  for (const filename of filenames) {
    await expect(driveSurface.locator(".drive-tile").filter({ hasText: filename })).toHaveCount(0);
  }

  await folderTile.dblclick();
  await expect(page.locator(".breadcrumb-current")).toContainText(folderName);
  for (const filename of filenames) {
    await expect(page.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
      timeout: 60_000,
    });
  }
});

test("external files can be dropped onto a breadcrumb and upload into that ancestor folder", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const parentFolderName = `ancestor-${uniqueId}`;
  const childFolderName = `nested-${uniqueId}`;
  const filename = `breadcrumb-drop-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(parentFolderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const parentFolderTile = driveSurface.locator(".drive-tile").filter({ hasText: parentFolderName }).first();
  await expect(parentFolderTile).toBeVisible({ timeout: 60_000 });
  await parentFolderTile.dblclick();
  await expect(page.locator(".breadcrumb-current")).toContainText(parentFolderName);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(childFolderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const childFolderTile = page.locator(".drive-tile").filter({ hasText: childFolderName }).first();
  await expect(childFolderTile).toBeVisible({ timeout: 60_000 });
  await childFolderTile.dblclick();
  await expect(page.locator(".breadcrumb-current")).toContainText(childFolderName);

  const parentBreadcrumb = page.getByRole("button", { name: parentFolderName }).first();
  const parentBreadcrumbSegment = parentBreadcrumb.locator("..");

  await parentBreadcrumbSegment.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File([payload.fileContents], payload.dropFilename, { type: "text/plain" }));
      node.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer }));
    },
    { dropFilename: filename, fileContents: `breadcrumb drop ${uniqueId}` },
  );
  await parentBreadcrumbSegment.evaluate(
    (node, payload) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File([payload.fileContents], payload.dropFilename, { type: "text/plain" }));
      node.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
    },
    { dropFilename: filename, fileContents: `breadcrumb drop ${uniqueId}` },
  );

  await expect(queuePanel).toBeVisible();
  await expect(queuePanel).toContainText(filename);
  await expect(queuePanel).toContainText(`Destination: ${parentFolderName}`);
  await expect(page.locator(".drive-tile").filter({ hasText: filename })).toHaveCount(0);

  await parentBreadcrumb.click();
  await expect(page.locator(".breadcrumb-current")).toContainText(parentFolderName);
  await expect(page.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });
});

test("duplicate folder creation stays local to the create-folder panel", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `Projects-${uniqueId}`;

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  await page.getByRole("button", { name: "New Folder" }).click();
  const createPanel = page.locator(".create-folder-panel").first();
  await createPanel.getByLabel("Folder name").fill(folderName);
  await createPanel.getByRole("button", { name: "Create Folder" }).click();

  await expect(createPanel.getByText(`A folder named "${folderName}" already exists in My Drive.`)).toBeVisible();
  await expect(page.locator(".error-banner")).toHaveCount(0);
});

test("same-name file move conflict stays local to the move form", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `Target-${uniqueId}`;
  const filename = `notes-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const folderTile = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();
  await expect(folderTile).toBeVisible({ timeout: 60_000 });
  await folderTile.dblclick();

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`target copy ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();
  await expect(page.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });

  await page.getByRole("button", { name: "Up", exact: true }).click();
  await expect(driveSurface.getByRole("heading", { name: "My Drive" })).toBeVisible();
  await expect(page.locator(".breadcrumbs")).toHaveCount(0);

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`root copy ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const rootFileTile = driveSurface.locator(".drive-tile").filter({ hasText: filename }).first();
  await expect(rootFileTile).toBeVisible({ timeout: 60_000 });

  await driveSurface.getByRole("button", { name: `More actions for ${filename}` }).first().click();
  await page.locator(".context-menu").getByRole("button", { name: "Move to…" }).click();

  const moveForm = rootFileTile.locator("form").first();
  await moveForm.getByRole("combobox").selectOption(folderName);
  await moveForm.getByRole("button", { name: "Move" }).click();

  await expect(moveForm.getByText(`A file named "${filename}" already exists in ${folderName}.`)).toBeVisible();
  await expect(page.locator(".error-banner")).toHaveCount(0);
});

test("single click selects a folder and double click navigates into it", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const folderName = `single-click-${uniqueId}`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();

  await openDriveWorkspace(page);

  await page.getByRole("button", { name: "New Folder" }).click();
  await page.getByLabel("Folder name").fill(folderName);
  await page.getByRole("button", { name: "Create Folder" }).click();

  const folderRow = driveSurface.locator(".drive-tile").filter({ hasText: folderName }).first();
  await expect(folderRow).toBeVisible({ timeout: 60_000 });

  await folderRow.click();

  const detailsPanel = page.locator("aside").filter({ has: page.getByRole("heading", { name: folderName }) }).first();
  await expect(detailsPanel).toBeVisible();
  await expect(page.locator(".breadcrumbs")).toHaveCount(0);

  await folderRow.dblclick();

  await expect(page.locator(".breadcrumb-current")).toContainText(folderName);
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: folderName }) }).first()).toBeVisible();
});

test("new folder action moved into drive header and sidebar can collapse", async ({ page }) => {
  await openDriveWorkspace(page);

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

  await openDriveWorkspace(page);

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

  await openDriveWorkspace(page);

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
  await openDriveWorkspace(page);

  await page.reload();

  await expect(page.getByText("demo")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toHaveCount(0);
});

});

test.describe("authenticated admin workspace", () => {
  test.use({ storageState: ADMIN_STORAGE_STATE });

test("admin login shows admin indicator", async ({ page }) => {
  await openAdminWorkspace(page);
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
  const detailToggle = systemHealth.locator("button.health-detail-toggle").first();
  await expect(detailToggle).toHaveAttribute("aria-expanded", "false");
  await detailToggle.click();
  await expect(detailToggle).toHaveAttribute("aria-expanded", "true");
});

});

test.describe("authenticated drive uploads and recovery", () => {
  test.use({ storageState: DEMO_STORAGE_STATE });

test("multiple files can be queued from the picker and complete in the shared upload queue", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const firstFilename = `queue-a-${uniqueId}.txt`;
  const secondFilename = `queue-b-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await openDriveWorkspace(page);

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
  await expect(queuePanel).toHaveCount(0, { timeout: 60_000 });
});

test("failed queued uploads stay visible with retry and dismiss actions", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `retry-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();
  let failNextUpload = true;

  await page.route("**/api/v1/files", async (route, request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/files" && failNextUpload) {
      failNextUpload = false;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "forced upload failure",
          code: "service_unavailable",
          category: "unavailable",
          recoverable: false,
        }),
      });
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

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
  await expect(page.locator(".error-banner")).toHaveCount(0);

  await queueRow.getByRole("button", { name: "Retry" }).click();

  await expect(driveSurface.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(queueRow).toHaveCount(0, { timeout: 60_000 });
});

test("oversized uploads show a friendly message when nginx returns an HTML 413 page", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `oversized-${uniqueId}.pdf`;
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await page.route("**/api/v1/files", async (route, request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/files") {
      await route.fulfill({
        status: 413,
        contentType: "text/html",
        body: `<html>
  <head><title>413 Request Entity Too Large</title></head>
  <body>
    <center><h1>413 Request Entity Too Large</h1></center>
    <hr><center>nginx/1.27.5</center>
  </body>
</html>`,
      });
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "application/pdf",
    buffer: Buffer.from(`oversized upload ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const queueRow = queuePanel.locator(".upload-queue-row").filter({ hasText: filename }).first();
  await expect(queueRow).toBeVisible({ timeout: 60_000 });
  await expect(queueRow).toContainText("This file is too large for the current upload limit.");
  await expect(queueRow).not.toContainText("413 Request Entity Too Large");
  await expect(queueRow).not.toContainText("<html>");
});

test("drive bootstrap survives activity service failure", async ({ page }) => {
  await page.route("**/api/v1/activity/me", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Activity backend unavailable",
        code: "service_unavailable",
        category: "unavailable",
        recoverable: false,
      }),
    });
  });

  await openDriveWorkspace(page);
  await expect(page.locator(".error-banner").filter({ hasText: "Drive load failed" })).toHaveCount(0);
});

test("trash view survives activity service failure", async ({ page }) => {
  let failActivity = false;

  await page.route("**/api/v1/activity/me", async (route) => {
    if (failActivity) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Activity backend unavailable",
          code: "service_unavailable",
          category: "unavailable",
          recoverable: false,
        }),
      });
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

  failActivity = true;
  await page.getByRole("button", { name: "Trash" }).click();

  await expect(page.getByRole("heading", { name: "Trash" })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".error-banner").filter({ hasText: "Trash load failed" })).toHaveCount(0);
});

test("successful uploads stay successful when activity refresh fails", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `post-upload-activity-${uniqueId}.txt`;
  const driveSurface = page.locator("section").filter({ has: page.getByRole("heading", { name: "My Drive" }) }).first();
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();
  let failActivity = false;

  await page.route("**/api/v1/activity/me", async (route) => {
    if (failActivity) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Activity backend unavailable",
          code: "service_unavailable",
          category: "unavailable",
          recoverable: false,
        }),
      });
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

  failActivity = true;
  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`post upload activity failure ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  await expect(driveSurface.locator(".drive-tile").filter({ hasText: filename }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(queuePanel.locator(".upload-queue-row").filter({ hasText: filename })).toHaveCount(0, {
    timeout: 60_000,
  });
  await expect(page.locator(".upload-queue-row").filter({ hasText: `Upload failed:` })).toHaveCount(0);
});

});

test.describe("authenticated admin recovery", () => {
  test.use({ storageState: ADMIN_STORAGE_STATE });

test("admin dashboard stays usable when one admin section fails", async ({ page }) => {
  await page.route("**/api/v1/admin/errors**", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Admin errors backend unavailable",
        code: "service_unavailable",
        category: "unavailable",
        recoverable: false,
      }),
    });
  });

  await openAdminWorkspace(page);
  await expect(page.getByText("Some admin data could not be refreshed: Errors. Displayed data may be incomplete.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Events" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Errors / Low-Level Info" })).toBeVisible();
  await expect(page.locator(".notice-card-warning").filter({ hasText: "Admin errors backend unavailable. Try again in a moment." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toHaveCount(0);
});

test("admin action failures stay local to the users section", async ({ page }) => {
  await page.route("**/api/v1/admin/users/*/reset-password", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Password reset backend unavailable",
        code: "service_unavailable",
        category: "unavailable",
        recoverable: false,
        context: {
          service: "keycloak",
          operation: "reset-password",
        },
      }),
    });
  });

  await openAdminWorkspace(page);
  const usersSection = page.locator(".content-surface").filter({ has: page.getByRole("heading", { name: "Users" }) }).first();
  await usersSection.getByRole("button", { name: "Reset Password" }).first().click();

  await expect(usersSection.locator(".notice-card-warning")).toContainText("Password reset backend unavailable. Service keycloak • Operation reset-password. Try again in a moment.");
  await expect(page.locator(".error-banner")).toHaveCount(0);
});

});

test.describe("authenticated drive network and auth recovery", () => {
  test.use({ storageState: DEMO_STORAGE_STATE });

test("upload network failures show a connection-oriented message", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const filename = `upload-network-${uniqueId}.txt`;
  const queuePanel = page.locator("section[aria-label='Upload Queue']").first();

  await page.route("**/api/v1/files", async (route, request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/files") {
      await route.abort("failed");
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

  await page.locator("#upload-file").setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(`upload network error ${uniqueId}`, "utf-8"),
  });
  await page.getByRole("button", { name: "Add to Upload Queue" }).click();

  const queueRow = queuePanel.locator(".upload-queue-row").filter({ hasText: filename }).first();
  await expect(queueRow).toBeVisible({ timeout: 60_000 });
  await expect(queueRow).toContainText("Upload could not reach the server. Check your connection and try again.");
});

test("search failures stay local to the search form and preserve the query", async ({ page }) => {
  const uniqueId = Date.now().toString();
  const query = `search-failure-${uniqueId}`;

  await page.route("**/api/v1/search**", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Search backend unavailable",
        code: "service_unavailable",
        category: "unavailable",
        recoverable: false,
      }),
    });
  });

  await openDriveWorkspace(page);

  await page.getByPlaceholder("Search files and folders").fill(query);
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.getByText("Search is temporarily unavailable. Try again in a moment.")).toBeVisible();
  await expect(page.getByPlaceholder("Search files and folders")).toHaveValue(query);
  await expect(page.locator(".error-banner")).toHaveCount(0);
});

test("auth api failures return the user to a relogin-oriented screen", async ({ page }) => {
  let failNextSearch = false;
  await page.route("**/api/v1/search**", async (route) => {
    if (failNextSearch) {
      failNextSearch = false;
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Invalid token",
          code: "invalid_token",
          category: "auth",
          recoverable: true,
        }),
      });
      return;
    }
    await route.fallback();
  });

  await openDriveWorkspace(page);

  failNextSearch = true;
  await page.getByPlaceholder("Search files and folders").fill("trigger-auth-recovery");
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toBeVisible();
  await expect(page.getByText("Your session expired or became invalid. Sign in again.")).toBeVisible();
});

});

test("profile menu logout returns to the unauthenticated entry screen", async ({ page }) => {
  await loginAs(page, "demo", "demo123");
  await expect(page.getByText("demo", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Open profile menu for demo" }).click();
  await page.getByRole("menuitem", { name: "Logout" }).click();

  await expect(page.getByRole("button", { name: "Log In With Keycloak" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Create Account" })).toBeVisible({ timeout: 60_000 });
});
