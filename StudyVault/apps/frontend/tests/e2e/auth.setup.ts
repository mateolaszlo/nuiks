import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ADMIN_STORAGE_STATE, DEMO_STORAGE_STATE, loginAs } from "./helpers";

test("capture demo and admin auth state", async ({ browser }) => {
  fs.mkdirSync(path.dirname(DEMO_STORAGE_STATE), { recursive: true });

  const demoContext = await browser.newContext();
  const demoPage = await demoContext.newPage();
  await loginAs(demoPage, "demo", "demo123");
  await expect(demoPage.getByText("demo", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(demoPage.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });
  await demoContext.storageState({ path: DEMO_STORAGE_STATE });
  await demoContext.close();

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await loginAs(adminPage, "admin", "admin123");
  await expect(adminPage.getByText("Admin Console")).toBeVisible({ timeout: 60_000 });
  await expect(adminPage.getByRole("heading", { name: "Users" })).toBeVisible({ timeout: 60_000 });
  await adminContext.storageState({ path: ADMIN_STORAGE_STATE });
  await adminContext.close();
});
