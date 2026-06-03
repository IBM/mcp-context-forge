/**
 * Playwright fixture that exposes a typed API mock helper.
 *
 * Uses `page.route()` so tests run without a live backend. The payload
 * shapes mirror `client/src/auth/AuthContext.tsx` (`User`, `LoginResponse`).
 */

import { test as base, expect, type Page, type Route } from "@playwright/test";

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
  mockMe(options?: { user?: MockUser; status?: number }): Promise<void>;
  mockUnauthorized(urlPattern: string | RegExp): Promise<void>;
}

export function createApiMock(page: Page): ApiMock {
  return {
    async mockLogin({
      user = DEFAULT_TEST_USER,
      status = 200,
      detail = "Invalid credentials",
    } = {}) {
      await page.route("**/app/auth/login", async (route) => {
        if (status === 200) {
          await route.fulfill({
            status,
            contentType: "application/json",
            body: JSON.stringify({
              user,
              mcpgateway_csrf_token: MOCK_CSRF_TOKEN,
            }),
          });
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail }),
        });
      });
    },

    async mockMe({ user = DEFAULT_TEST_USER, status = 200 } = {}) {
      const fulfillUser = async (route: Route) => {
        if (status === 200) {
          await route.fulfill({
            status,
            contentType: "application/json",
            body: JSON.stringify(user),
          });
          return;
        }
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unauthorized" }),
        });
      };

      await page.route("**/app/auth/me", fulfillUser);
      await page.route("**/auth/email/me", fulfillUser);
      await page.route("**/auth/me", fulfillUser);
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
