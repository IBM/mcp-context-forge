/**
 * Authenticated-page fixture.
 *
 * Extends the base Playwright test with:
 *   - a `page` that has the bearer token pre-seeded in sessionStorage, and
 *   - an `apiMock` with `/auth/me` + `/auth/login` pre-stubbed.
 *
 * Tests import from here when they need to skip the login form and land
 * directly on an authenticated route.
 */

import { test as base } from "@playwright/test";
import { TOKEN_STORAGE_KEY } from "../utils/paths";
import { createApiMock, MOCK_TOKEN, type ApiMock } from "./api-mock";

type AuthFixtures = {
  apiMock: ApiMock;
};

export const test = base.extend<AuthFixtures>({
  page: async ({ page }, use) => {
    // Seed token before any page script runs so AuthContext rehydrates
    // as "authenticated" on first render.
    await page.addInitScript(
      ([key, token]) => {
        window.sessionStorage.setItem(key, token);
      },
      [TOKEN_STORAGE_KEY, MOCK_TOKEN],
    );
    await use(page);
  },
  apiMock: async ({ page }, use) => {
    const mock = createApiMock(page);
    await mock.mockMe();
    await mock.mockLogin();
    await use(mock);
  },
});

export { expect } from "@playwright/test";
