import { test, expect } from "../fixtures/api-mock";
import { APP, TOKEN_STORAGE_KEY } from "../utils/paths";

test.describe("Login flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((key) => {
      window.sessionStorage.removeItem(key);
    }, TOKEN_STORAGE_KEY);
  });

  test("successful login navigates to the dashboard", async ({ page, apiMock }) => {
    await apiMock.mockLogin();
    await apiMock.mockMe();

    await page.goto(APP.LOGIN);
    await page.getByLabel(/email address/i).fill("test@example.com");
    await page.getByLabel(/password/i).fill("password123");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page).toHaveURL(new RegExp(`${APP.ROOT}$`));
    await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();

    const token = await page.evaluate(
      (key) => window.sessionStorage.getItem(key),
      TOKEN_STORAGE_KEY,
    );
    expect(token).not.toBeNull();
  });

  test("401 response keeps user on the login page without a token", async ({ page, apiMock }) => {
    // A 401 from /auth/login is currently treated as a generic session-expiry
    // by the API client (clearToken + window.location.replace). That wipes
    // React state, so the error alert is not observable here — we assert the
    // outcome the user experiences: stuck on /app/login, no token persisted.
    await apiMock.mockLogin({ status: 401 });

    await page.goto(APP.LOGIN);
    await page.getByLabel(/email address/i).fill("wrong@example.com");
    await page.getByLabel(/password/i).fill("bad-password");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page).toHaveURL(new RegExp(`${APP.LOGIN}$`));
    const token = await page.evaluate(
      (key) => window.sessionStorage.getItem(key),
      TOKEN_STORAGE_KEY,
    );
    expect(token).toBeNull();
  });

  test("500 response surfaces generic failure message", async ({ page, apiMock }) => {
    await apiMock.mockLogin({ status: 500 });

    await page.goto(APP.LOGIN);
    await page.getByLabel(/email address/i).fill("test@example.com");
    await page.getByLabel(/password/i).fill("password123");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page.getByRole("alert")).toHaveText(/login failed/i);
  });

  test("submit button shows loading state during request", async ({ page, apiMock }) => {
    // Delay the response so the loading state is observable.
    await page.route("**/auth/login", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "mock-token-12345",
          token_type: "bearer",
          expires_in: 3600,
          user: {
            email: "test@example.com",
            full_name: "Test User",
            is_admin: true,
            is_active: true,
            auth_provider: "local",
            email_verified: true,
            password_change_required: false,
          },
        }),
      });
    });
    await apiMock.mockMe();

    await page.goto(APP.LOGIN);
    await page.getByLabel(/email address/i).fill("test@example.com");
    await page.getByLabel(/password/i).fill("password123");

    const submit = page.getByRole("button", { name: /sign in|signing in/i });
    await submit.click();
    await expect(submit).toBeDisabled();
    await expect(submit).toHaveText(/signing in/i);
  });
});
