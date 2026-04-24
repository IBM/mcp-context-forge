import { test, expect } from "../fixtures/api-mock";
import { APP, TOKEN_STORAGE_KEY } from "../utils/paths";

test.describe("Forgot password navigation", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe({ status: 401 });
    await page.addInitScript((key) => {
      window.sessionStorage.removeItem(key);
    }, TOKEN_STORAGE_KEY);
  });

  test("login → forgot password link navigates to reset flow", async ({ page }) => {
    await page.goto(APP.LOGIN);
    await page.getByRole("button", { name: /forgot password/i }).click();
    await expect(page).toHaveURL(new RegExp(`${APP.FORGOT_PASSWORD}$`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
});
