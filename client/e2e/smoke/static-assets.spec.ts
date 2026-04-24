import { test, expect } from "../fixtures/api-mock";
import { APP } from "../utils/paths";

/**
 * Guards against the class of regressions where a misconfigured Vite base
 * path, broken import, or missing public asset ships 4xx/5xx on first paint.
 * The favicon is intentionally excluded because it is served by the gateway
 * in production, not the Vite dev server.
 */
test.describe("Static assets (smoke)", () => {
  test("no 4xx/5xx for JS, CSS, or fonts on initial load", async ({ page, apiMock }) => {
    await apiMock.mockMe({ status: 401 });

    const failures: string[] = [];
    page.on("response", (response) => {
      const url = response.url();
      const status = response.status();
      if (status < 400) return;
      if (url.includes("favicon")) return;
      if (/\/(auth|api)\//.test(url)) return; // intentional mocked failures
      failures.push(`${status} ${url}`);
    });

    await page.goto(APP.LOGIN);
    await page.waitForLoadState("networkidle");

    expect(failures, `Asset failures:\n${failures.join("\n")}`).toHaveLength(0);
  });
});
