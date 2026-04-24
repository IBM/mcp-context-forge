import { test, expect } from "../fixtures/api-mock";
import { APP } from "../utils/paths";

test.describe("App loading (smoke)", () => {
  test("loads /app without JavaScript errors", async ({ page, apiMock }) => {
    // Unauthenticated entry point: auth guard will redirect to /app/login,
    // which fetches nothing, but mock /auth/me defensively in case a token
    // sneaks in from a previous worker.
    await apiMock.mockMe({ status: 401 });

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => {
      pageErrors.push(`${err.name}: ${err.message}`);
    });

    await page.goto(APP.ROOT);
    await page.waitForLoadState("networkidle");

    expect(pageErrors, `Uncaught page errors:\n${pageErrors.join("\n")}`).toHaveLength(0);
    expect(consoleErrors, `Console errors:\n${consoleErrors.join("\n")}`).toHaveLength(0);
  });

  test("bare /app redirects into /app/ then to /app/login", async ({ page, apiMock }) => {
    await apiMock.mockMe({ status: 401 });

    await page.goto("/app");
    await expect(page).toHaveURL(/\/app\/login$/);
  });
});
