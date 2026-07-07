import { test, expect } from "./fixtures/api-mock";
import { APP } from "./utils/paths";

test.describe("Global search", () => {
  test.beforeEach(async ({ apiMock }) => {
    await apiMock.mockMe();
  });

  test("searches globally from the header and navigates to the selected result", async ({
    page,
  }) => {
    let searchRequestUrl = "";

    await page.route("**/gateways?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ gateways: [], nextCursor: null }),
      });
    });
    await page.route("**/tools?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "tool-other",
            name: "Other Tool",
            originalName: "Other Tool",
            description: "Another tool in the same group",
            gatewayId: "gateway-weather",
            gatewaySlug: "weather-server",
            customName: "Other Tool",
            customNameSlug: "other-tool",
            enabled: true,
            reachable: true,
            executionCount: 0,
            tags: [],
            integrationType: "MCP",
            requestType: "SSE",
            createdAt: "2026-07-06T10:00:00Z",
            updatedAt: "2026-07-06T10:00:00Z",
          },
          {
            id: "tool-weather",
            name: "Weather Tool",
            originalName: "Weather Tool",
            description: "Forecast lookup",
            gatewayId: "gateway-weather",
            gatewaySlug: "weather-server",
            customName: "Weather Tool",
            customNameSlug: "weather-tool",
            enabled: true,
            reachable: true,
            executionCount: 0,
            tags: [],
            integrationType: "MCP",
            requestType: "SSE",
            createdAt: "2026-07-06T10:00:00Z",
            updatedAt: "2026-07-06T10:00:00Z",
          },
        ]),
      });
    });
    await page.route("**/admin/search?*", async (route) => {
      searchRequestUrl = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: "weather",
          entity_types: ["tools"],
          limit_per_type: 8,
          results: {},
          groups: [
            {
              entity_type: "tools",
              count: 1,
              items: [
                {
                  id: "tool-weather",
                  name: "Weather Tool",
                  description: "Forecast lookup",
                },
              ],
            },
          ],
          items: [],
          count: 1,
        }),
      });
    });

    await page.goto(APP.SERVERS);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Search" }).click();
    const searchBox = page.getByRole("searchbox", { name: "Search" });
    await searchBox.pressSequentially("w");
    await expect(searchBox).toBeFocused();
    await searchBox.pressSequentially("eather");

    await expect(page.getByText("Weather Tool")).toBeVisible();
    expect(searchRequestUrl).toContain("/admin/search?");
    expect(searchRequestUrl).toContain("q=weather");
    expect(searchRequestUrl).toContain("entity_types=");

    await page.getByText("Weather Tool").click();

    await expect(page).toHaveURL(/\/app\/tools\?selected=tool-weather&search=weather$/);
    await expect(page.getByRole("region", { name: /Tools for weather-server/i })).toBeVisible();
    await expect(page.locator('tr[data-state="selected"]')).toContainText("Weather Tool");
  });
});
