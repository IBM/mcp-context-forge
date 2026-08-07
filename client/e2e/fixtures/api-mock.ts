/**
 * Playwright fixture that exposes a typed API mock helper.
 *
 * Uses `page.route()` so tests run without a live backend. The payload
 * shapes mirror the BFF's auth routes (client/server/src/routes/auth/) and
 * `client/src/auth/AuthContext.tsx` (`User`, `LoginResponse`, `SessionResponse`).
 */

import { test as base, expect, type Page } from "@playwright/test";

export interface MockUser {
  email: string;
  full_name: string | null;
  is_admin: boolean;
  is_active: boolean;
  auth_provider: string;
  email_verified: boolean;
  password_change_required: boolean;
}

export const DEFAULT_TEST_USER: MockUser = {
  email: "test@example.com",
  full_name: "Test User",
  is_admin: true,
  is_active: true,
  auth_provider: "local",
  email_verified: true,
  password_change_required: false,
};

export const MOCK_CSRF_TOKEN = "mock-csrf-token";

export interface ApiMock {
  mockLogin(options?: { user?: MockUser; status?: number; detail?: string }): Promise<void>;
  /**
   * Mocks GET /auth/session, the SPA's bootstrap probe. Unlike the old
   * cookie-auth /app/auth/me, the BFF's /auth/session never 401s — it
   * always returns 200 with an `authenticated` flag. Pass
   * `authenticated: false` for the logged-out case; a bare call defaults to
   * a logged-in DEFAULT_TEST_USER.
   */
  mockSession(options?: { user?: MockUser; authenticated?: boolean }): Promise<void>;
  mockUnauthorized(urlPattern: string | RegExp): Promise<void>;
}

export function createApiMock(page: Page): ApiMock {
  return {
    async mockLogin({
      user = DEFAULT_TEST_USER,
      status = 200,
      detail = "Invalid credentials",
    } = {}) {
      await page.route("**/auth/login", async (route) => {
        if (status === 200) {
          await route.fulfill({
            status,
            contentType: "application/json",
            body: JSON.stringify({
              user,
              csrfToken: MOCK_CSRF_TOKEN,
            }),
          });
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ error: "login_failed", detail }),
        });
      });
    },

    async mockSession({ user = DEFAULT_TEST_USER, authenticated = true } = {}) {
      await page.route("**/auth/session", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            authenticated
              ? { authenticated: true, user, csrfToken: MOCK_CSRF_TOKEN }
              : { authenticated: false },
          ),
        });
      });
    },

    async mockUnauthorized(urlPattern) {
      await page.route(urlPattern, async (route) => {
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unauthorized" }),
        });
      });
    },
  };
}

type Fixtures = {
  apiMock: ApiMock;
};

export const test = base.extend<Fixtures>({
  apiMock: async ({ page }, use) => {
    await use(createApiMock(page));
  },
});

export { expect };
