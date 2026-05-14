import { expect, type Page } from "@playwright/test";
import path from "node:path";

export const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:8080";
export const ELASTICSEARCH_URL = process.env.ELASTICSEARCH_URL ?? "http://localhost:9200";
export const DEMO_STORAGE_STATE = path.resolve(process.cwd(), "tests/e2e/.auth/demo.json");
export const ADMIN_STORAGE_STATE = path.resolve(process.cwd(), "tests/e2e/.auth/admin.json");

export async function loginAs(page: Page, username: string, password: string) {
  await page.goto(BASE_URL);
  const loginButton = page.getByRole("button", { name: "Log In With Keycloak" });
  const usernameInput = page.locator("#username");
  const dashboardIdentity = page.getByText(username, { exact: true }).first();
  const driveWorkspace = page.getByRole("heading", { name: "My Drive" }).first();
  const adminWorkspace = page.getByRole("heading", { name: "Users" }).first();

  const entryState = await Promise.any([
    loginButton.waitFor({ state: "visible", timeout: 30_000 }).then(() => "login"),
    usernameInput.waitFor({ state: "visible", timeout: 30_000 }).then(() => "keycloak"),
    dashboardIdentity.waitFor({ state: "visible", timeout: 30_000 }).then(() => "ready"),
    driveWorkspace.waitFor({ state: "visible", timeout: 30_000 }).then(() => "ready"),
    adminWorkspace.waitFor({ state: "visible", timeout: 30_000 }).then(() => "ready"),
  ]);

  if (entryState === "ready") {
    return;
  }
  if (entryState === "login") {
    await expect(loginButton).toBeVisible();
    await expect(page.getByRole("button", { name: "Create Account" })).toBeVisible();
    await loginButton.click();
  }
  await expect(page).toHaveURL(/\/realms\/studyvault\//, { timeout: 30_000 });
  await expect(usernameInput).toBeVisible();
  await usernameInput.fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
}

export async function openDriveWorkspace(page: Page, username = "demo") {
  await page.goto(BASE_URL);
  await expect(page.getByText(username, { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My Drive" })).toBeVisible({ timeout: 60_000 });
}

export async function openAdminWorkspace(page: Page) {
  await page.goto(BASE_URL);
  await expect(page.getByRole("button", { name: "Users" }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible({ timeout: 60_000 });
}
