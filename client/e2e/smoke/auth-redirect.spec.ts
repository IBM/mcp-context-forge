import { test, expect } from "../fixtures/api-mock";
import { APP, TOKEN_STORAGE_KEY } from "../utils/paths";

test.describe("Unauthenticated access (smoke)", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe({ status: 401 });
    await page.addInitScript((key) => {
      window.sessionStorage.removeItem(key);
    }, TOKEN_STORAGE_KEY);
  });

  test("dashboard redirects to login", async ({ page }) => {
    await page.goto(APP.ROOT);
    await expect(page).toHaveURL(new RegExp(`${APP.LOGIN}$`));
  });

  test("protected route redirects to login", async ({ page }) => {
    await page.goto(APP.GATEWAYS);
    await expect(page).toHaveURL(new RegExp(`${APP.LOGIN}$`));
  });

  test("login page renders form fields", async ({ page }) => {
    await page.goto(APP.LOGIN);

    await expect(page.getByRole("heading", { level: 1, name: /sign in/i })).toBeVisible();
    await expect(page.getByLabel(/email address/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /^sign in$/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /forgot password/i })).toBeVisible();
  });

  test("public routes are reachable without auth", async ({ page }) => {
    await page.goto(APP.FORGOT_PASSWORD);
    await expect(page).toHaveURL(new RegExp(`${APP.FORGOT_PASSWORD}$`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
});
