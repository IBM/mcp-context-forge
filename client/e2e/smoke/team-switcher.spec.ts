import { test, expect } from "../fixtures/api-mock";
import { APP } from "../utils/paths";

test.describe("TeamSwitcher component (smoke)", () => {
  test("renders and displays teams from API", async ({ page, apiMock }) => {
    // Mock authenticated user
    await apiMock.mockMe();

    // Mock /teams endpoint
    await page.route("**/teams", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          teams: [
            { id: "1", name: "Engineering" },
            { id: "2", name: "Marketing" },
          ],
        }),
      });
    });

    // Navigate to a page with sidebar
    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // Wait for TeamSwitcher to be visible
    const trigger = page.getByRole("button", { name: /all teams/i });
    await expect(trigger).toBeVisible({ timeout: 10000 });

    // Click to open dropdown
    await trigger.click();

    // Wait for dropdown menu to appear
    await expect(page.getByRole("menu")).toBeVisible();

    // Should see teams in dropdown
    await expect(page.getByText("Engineering")).toBeVisible();
    await expect(page.getByText("Marketing")).toBeVisible();
  });

  test("displays error message when teams fail to load", async ({ page, apiMock }) => {
    // Mock authenticated user
    await apiMock.mockMe();

    // Mock /teams endpoint with error
    await page.route("**/teams", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal server error" }),
      });
    });

    await page.goto(APP.GATEWAYS);
    await page.waitForLoadState("networkidle");

    // TeamSwitcher should still render with "All teams"
    const trigger = page.getByRole("button", { name: /all teams/i });
    await expect(trigger).toBeVisible({ timeout: 10000 });

    // Open dropdown
    await trigger.click();
    await expect(page.getByRole("menu")).toBeVisible();

    // Should show error message
    await expect(page.getByText("Failed to load teams")).toBeVisible();
  });
});
