/**
 * Authenticated-page fixture.
 *
 * Extends the base Playwright test with:
 *   - an `apiMock` with `/app/auth/me` + `/app/auth/login` pre-stubbed.
 *
 * Tests import from here when they need to skip the login form and land
 * directly on an authenticated route.
 */

import { test as base } from "@playwright/test";
import { createApiMock, type ApiMock } from "./api-mock";

type AuthFixtures = {
  apiMock: ApiMock;
};

export const test = base.extend<AuthFixtures>({
  page: async ({ page }, use) => {
    const mock = createApiMock(page);
    await mock.mockMe();
    await mock.mockLogin();
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
