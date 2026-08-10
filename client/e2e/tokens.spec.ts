import { test, expect } from "./fixtures/api-mock";
import type { TokenResponse } from "../src/types/token";

// The API Tokens surface lives in the Settings shell (see src/pages/Settings.tsx).
const TOKENS_TAB = "/app/settings/tokens";

// URL predicates match the API endpoints regardless of an optional `/api` proxy
// prefix. They are anchored so they never match the SPA route
// (`/app/settings/tokens`) or Vite-served source modules
// (`/src/components/tokens/TokenForm.tsx`).
const TOKENS_ROUTE = (url: URL) => /^(?:\/api)?\/tokens$/.test(url.pathname); // GET list + POST create
const TOKEN_ID_ROUTE = (url: URL) => /^(?:\/api)?\/tokens\/[^/]+$/.test(url.pathname); // DELETE {id}
const TEAMS_ROUTE = (url: URL) => /^(?:\/api)?\/teams$/.test(url.pathname);

const MOCK_TEAMS = {
  teams: [{ id: "team-1", name: "devteam" }],
};

function makeToken(overrides: Partial<TokenResponse> = {}): TokenResponse {
  return {
    id: "tok-1",
    name: "CI token",
    description: "used by ci",
    user_email: "test@example.com",
    team_id: "team-1",
    server_id: null,
    resource_scopes: [],
    ip_restrictions: [],
    time_restrictions: {},
    usage_limits: {},
    created_at: "2026-08-01T10:00:00Z",
    expires_at: new Date(Date.now() + 28 * 86_400_000).toISOString(),
    last_used: null,
    is_active: true,
    is_revoked: false,
    tags: [],
    ...overrides,
  };
}

function listBody(tokens: TokenResponse[]) {
  return JSON.stringify({ tokens, total: tokens.length, limit: 0, offset: 0 });
}

test.describe("API Tokens", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();
    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
    await page.route(TEAMS_ROUTE, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_TEAMS),
      });
    });
  });

  test("lists tokens with their team name", async ({ page }) => {
    await page.route(TOKENS_ROUTE, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: listBody([makeToken()]),
      });
    });

    await page.goto(TOKENS_TAB);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("tab", { name: "API tokens" })).toBeVisible();
    await expect(page.getByText("CI token")).toBeVisible();
    // team_id -> team name mapping comes from the /teams query.
    await expect(page.getByText("devteam")).toBeVisible();
  });

  test("shows the empty state when there are no tokens", async ({ page }) => {
    await page.route(TOKENS_ROUTE, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: listBody([]),
      });
    });

    await page.goto(TOKENS_TAB);
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "Generate API token" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Generate token" })).toBeVisible();
  });

  test("creates a token and reveals the one-time secret", async ({ page }) => {
    let postCount = 0;
    let postedName: string | undefined;

    await page.route(TOKENS_ROUTE, async (route) => {
      if (route.request().method() === "POST") {
        postCount++;
        postedName = (route.request().postDataJSON() as { name?: string }).name;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            access_token: "eyJ-mock-access-token",
            token: makeToken({ id: "tok-new", name: "release token" }),
          }),
        });
        return;
      }
      // GET list — starts empty.
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: listBody([]),
      });
    });

    await page.goto(TOKENS_TAB);
    await page.waitForLoadState("networkidle");

    // Empty state -> open the create form.
    await page.getByRole("button", { name: "Generate token" }).click();
    await expect(page.getByRole("heading", { name: "Generate API token" })).toBeVisible();

    await page.locator("#token-name").fill("release token");
    await page.getByRole("button", { name: "Generate token" }).click();

    await expect.poll(() => postCount).toBe(1);
    expect(postedName).toBe("release token");

    // One-time secret dialog.
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Save token in a secure place. It won't be viewable again."),
    ).toBeVisible();
    await expect(dialog.getByText("eyJ-mock-access-token")).toBeVisible();

    // The dialog has both a footer "Close" button and a built-in X (also labelled
    // "Close"); the footer button renders first.
    await dialog.getByRole("button", { name: "Close" }).first().click();
    await expect(dialog).not.toBeVisible();
  });

  test("deletes a token after confirmation", async ({ page }) => {
    let deleteCount = 0;

    await page.route(TOKENS_ROUTE, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: listBody([makeToken()]),
      });
    });
    await page.route(TOKEN_ID_ROUTE, async (route) => {
      expect(route.request().method()).toBe("DELETE");
      deleteCount++;
      await route.fulfill({ status: 204 });
    });

    await page.goto(TOKENS_TAB);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("CI token")).toBeVisible();

    await page.getByRole("button", { name: "Actions for CI token" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText("This revokes access immediately and can't be undone."),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect.poll(() => deleteCount).toBe(1);
    // Optimistically removed from the list.
    await expect(page.getByText("CI token")).not.toBeVisible();
  });
});
