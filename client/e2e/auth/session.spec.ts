import { test, expect } from "../fixtures/auth";
import { APP, TOKEN_STORAGE_KEY } from "../utils/paths";

test.describe("Authenticated session", () => {
  test("pre-seeded token lets a user reach the dashboard", async ({ page }) => {
    await page.goto(APP.ROOT);
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
    const token = await page.evaluate(
      (key) => window.sessionStorage.getItem(key),
      TOKEN_STORAGE_KEY,
    );
    expect(token).toBe("mock-token-12345");
  });
});
