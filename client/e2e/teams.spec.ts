import { test, expect } from "./fixtures/api-mock";
import type { Page, Locator } from "@playwright/test";
import { APP } from "./utils/paths";
import type { Team, TeamMember } from "../src/types/team";
import type { TeamCreateRequest, TeamMemberAddRequest } from "../src/generated/types";

const MOCK_TEAM: Team = {
  id: "team-1",
  name: "Engineering",
  slug: "engineering",
  description: "Core engineering team",
  created_by: "admin@example.com",
  is_personal: false,
  visibility: "private",
  max_members: 50,
  member_count: 5,
  created_at: "2026-06-01T10:00:00Z",
  updated_at: "2026-06-15T14:30:00Z",
  is_active: true,
};

const MOCK_TEAM_PUBLIC: Team = {
  id: "team-2",
  name: "Public Team",
  slug: "public-team",
  description: "Public team for everyone",
  created_by: "admin@example.com",
  is_personal: false,
  visibility: "public",
  max_members: 100,
  member_count: 10,
  created_at: "2026-06-02T10:00:00Z",
  updated_at: "2026-06-16T14:30:00Z",
  is_active: true,
};

const MOCK_TEAM_3: Team = {
  id: "team-3",
  name: "Design Team",
  slug: "design-team",
  description: "Design and UX team",
  created_by: "admin@example.com",
  is_personal: false,
  visibility: "private",
  max_members: 30,
  member_count: 8,
  created_at: "2026-06-03T10:00:00Z",
  updated_at: "2026-06-17T14:30:00Z",
  is_active: true,
};

const MOCK_MEMBER: TeamMember = {
  user_email: "john@example.com",
  role: "member",
  joined_at: "2026-06-05T09:00:00Z",
  invited_by: "admin@example.com",
};

const MOCK_MEMBER_2: TeamMember = {
  user_email: "jane@example.com",
  role: "owner",
  joined_at: "2026-06-06T09:00:00Z",
  invited_by: "admin@example.com",
};

const MOCK_TEAM_ROUTE = `**/teams/${MOCK_TEAM.id}`;
const MOCK_TEAM_MEMBERS_ROUTE = `**/teams/${MOCK_TEAM.id}/members`;

// Combobox placeholders differ by context: TeamForm uses "Name or email" while
// ManageTeamMembersDialog uses "Name or email..." (see teams.json).
const TEAM_FORM_MEMBER_INPUT = 'input[placeholder="Name or email"]';
const MANAGE_MEMBERS_INPUT = 'input[placeholder="Name or email..."]';

/** Selects an option from a Radix Select by clicking its trigger, then the option by exact text. */
async function selectRadixOption(page: Page, trigger: Locator, optionName: string) {
  await trigger.click();
  await page.getByRole("option", { name: optionName, exact: true }).click();
}

/** Picks a member from a Combobox's directory dropdown by typing a search term and clicking the match. */
async function pickComboboxOption(
  page: Page,
  input: Locator,
  searchTerm: string,
  expectedEmail: string,
) {
  await input.fill(searchTerm);
  const listboxId = await input.getAttribute("aria-controls");
  await page.locator(`[id="${listboxId}"]`).getByText(expectedEmail).click();
}

test.describe("Teams page", () => {
  test.beforeEach(async ({ page, apiMock }) => {
    await apiMock.mockMe();

    await page.addInitScript(() => {
      sessionStorage.setItem("mcpgateway_token", "mock-token-12345");
    });
  });

  test.describe("Display & List", () => {
    test("shows teams list with details", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM, MOCK_TEAM_PUBLIC] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      const main = page.getByRole("main");
      await expect(page.getByRole("heading", { name: "Teams" })).toBeVisible();
      await expect(main.getByText("Engineering")).toBeVisible();
      await expect(page.getByRole("cell", { name: "5", exact: true })).toBeVisible();
      await expect(main.getByRole("cell", { name: "private", exact: true })).toBeVisible();
      await expect(main.getByText("Public Team")).toBeVisible();
      await expect(main.getByRole("cell", { name: "public", exact: true })).toBeVisible();

      // Description is revealed via a popover, not shown inline in the row.
      await page.getByRole("button", { name: "View description for Engineering" }).click();
      await expect(page.getByText("Core engineering team")).toBeVisible();
    });

    test("shows empty state with create button", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("No teams yet")).toBeVisible();
      await expect(
        page.getByText("Create your first team to collaborate with others."),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Create Team" })).toBeVisible();
      await expect(page.getByRole("table")).not.toBeVisible();
    });

    test("loads more teams with pagination", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        const url = new URL(route.request().url());
        const hasCursor = url.searchParams.has("cursor");

        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            hasCursor
              ? { teams: [MOCK_TEAM_3] }
              : { teams: [MOCK_TEAM, MOCK_TEAM_PUBLIC], nextCursor: "cursor-1" },
          ),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Engineering")).toBeVisible();
      await expect(page.getByText("Public Team")).toBeVisible();
      await expect(page.getByText("Design Team")).not.toBeVisible();

      const loadMoreButton = page.getByRole("button", { name: "Load more teams" });
      await expect(loadMoreButton).toBeVisible();
      await loadMoreButton.click();

      await expect(page.getByText("Design Team")).toBeVisible();
      await expect(page.getByText("Engineering")).toBeVisible();
      await expect(loadMoreButton).not.toBeVisible();
    });
  });

  test.describe("Create Team", () => {
    test("creates team without members", async ({ page }) => {
      let createCount = 0;
      let teams: Team[] = [];

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams }),
        });
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          createCount++;
          const body = JSON.parse(route.request().postData() || "{}");
          const newTeam: Team = {
            id: "team-new",
            name: body.name,
            slug: body.name.toLowerCase().replace(/\s+/g, "-"),
            description: body.description,
            created_by: "test@example.com",
            is_personal: false,
            visibility: body.visibility,
            max_members: body.max_members,
            member_count: 0,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            is_active: true,
          };
          teams = [...teams, newTeam];
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(newTeam),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();
      await expect(page.getByRole("heading", { name: "Create Team" })).toBeVisible();

      await page.locator("#team-name").fill("New Team");
      await page.getByRole("textbox", { name: "Description" }).fill("A new team");
      await page.getByText("Public", { exact: true }).click();
      await selectRadixOption(page, page.locator("#max-members"), "25");

      await page.getByRole("button", { name: "Create Team" }).click();

      await expect.poll(() => createCount).toBe(1);
      await expect(page.getByRole("heading", { name: "Teams" })).toBeVisible();
      await expect(page.getByText("New Team")).toBeVisible();
    });

    test("creates team with single member", async ({ page }) => {
      let createCount = 0;
      let requestBody: TeamCreateRequest;
      const memberRequests: TeamMemberAddRequest[] = [];

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [{ email: "member1@example.com", full_name: "Member One" }],
          }),
        });
      });

      // Membership isn't sent with team creation; each row is added via its own
      // POST to /teams/{id}/members after the team is created.
      await page.route("**/teams/team-new/members", async (route) => {
        if (route.request().method() === "POST") {
          memberRequests.push(JSON.parse(route.request().postData() || "{}"));
          await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
        } else {
          await route.fallback();
        }
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          createCount++;
          requestBody = JSON.parse(route.request().postData() || "{}");
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              id: "team-new",
              name: requestBody.name,
              slug: "team-with-member",
              description: requestBody.description,
              created_by: "test@example.com",
              is_personal: false,
              visibility: requestBody.visibility,
              max_members: requestBody.max_members,
              member_count: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              is_active: true,
            } satisfies Team),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();

      await page.locator("#team-name").fill("Team With Member");
      await page.getByRole("textbox", { name: "Description" }).fill("Team with one member");

      // The form starts with one editable member row already present.
      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).first(),
        "member1",
        "member1@example.com",
      );
      await selectRadixOption(page, page.locator('[data-slot="select-trigger"]').first(), "member");

      await page.getByRole("button", { name: "Create Team" }).click();

      await expect.poll(() => createCount).toBe(1);
      await expect.poll(() => memberRequests).toHaveLength(1);
      expect(memberRequests[0].email).toBe("member1@example.com");
      expect(memberRequests[0].role).toBe("member");
    });

    test("creates team with multiple members (mixed roles)", async ({ page }) => {
      let createCount = 0;
      let requestBody: TeamCreateRequest;
      const memberRequests: TeamMemberAddRequest[] = [];

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [
              { email: "member1@example.com", full_name: "Member One" },
              { email: "member2@example.com", full_name: "Member Two" },
              { email: "owner1@example.com", full_name: "Owner One" },
            ],
          }),
        });
      });

      await page.route("**/teams/team-new/members", async (route) => {
        if (route.request().method() === "POST") {
          memberRequests.push(JSON.parse(route.request().postData() || "{}"));
          await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
        } else {
          await route.fallback();
        }
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          createCount++;
          requestBody = JSON.parse(route.request().postData() || "{}");
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              id: "team-new",
              name: requestBody.name,
              slug: "team-multi-members",
              description: requestBody.description,
              created_by: "test@example.com",
              is_personal: false,
              visibility: requestBody.visibility,
              max_members: requestBody.max_members,
              member_count: 3,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              is_active: true,
            } satisfies Team),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();

      await page.locator("#team-name").fill("Multi Member Team");

      // Row 0 is present by default; add two more rows for a total of three.
      await page.getByRole("button", { name: "Add team member" }).click();
      await page.getByRole("button", { name: "Add team member" }).click();

      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).nth(0),
        "member1",
        "member1@example.com",
      );
      await selectRadixOption(page, page.locator('[data-slot="select-trigger"]').nth(0), "member");

      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).nth(1),
        "member2",
        "member2@example.com",
      );
      await selectRadixOption(page, page.locator('[data-slot="select-trigger"]').nth(1), "member");

      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).nth(2),
        "owner1",
        "owner1@example.com",
      );
      await selectRadixOption(page, page.locator('[data-slot="select-trigger"]').nth(2), "owner");

      await page.getByRole("button", { name: "Create Team" }).click();

      await expect.poll(() => createCount).toBe(1);
      await expect.poll(() => memberRequests).toHaveLength(3);
      expect(memberRequests.filter((m) => m.role === "member")).toHaveLength(2);
      expect(memberRequests.filter((m) => m.role === "owner")).toHaveLength(1);
    });

    test("name is required (validation)", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();

      // The submit button stays disabled until a name is entered, so validation
      // is exercised by attempting to submit the (disabled) form directly.
      const submitButton = page.getByRole("button", { name: "Create Team" });
      await expect(submitButton).toBeDisabled();
    });

    test("removes member row before submit", async ({ page }) => {
      let createCount = 0;
      let requestBody: TeamCreateRequest;
      const memberRequests: TeamMemberAddRequest[] = [];

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [
              { email: "member1@example.com", full_name: "Member One" },
              { email: "member2@example.com", full_name: "Member Two" },
            ],
          }),
        });
      });

      await page.route("**/teams/team-new/members", async (route) => {
        if (route.request().method() === "POST") {
          memberRequests.push(JSON.parse(route.request().postData() || "{}"));
          await route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
        } else {
          await route.fallback();
        }
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          createCount++;
          requestBody = JSON.parse(route.request().postData() || "{}");
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              id: "team-new",
              name: requestBody.name,
              slug: "team-removed-member",
              created_by: "test@example.com",
              is_personal: false,
              visibility: "private",
              member_count: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              is_active: true,
            } satisfies Team),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();

      await page.locator("#team-name").fill("Team Remove Test");

      // Row 0 is present by default; add one more row for a total of two.
      await page.getByRole("button", { name: "Add team member" }).click();

      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).nth(0),
        "member1",
        "member1@example.com",
      );
      await pickComboboxOption(
        page,
        page.locator(TEAM_FORM_MEMBER_INPUT).nth(1),
        "member2",
        "member2@example.com",
      );

      await page.getByRole("button", { name: "Remove" }).first().click();

      await page.getByRole("button", { name: "Create Team" }).click();

      await expect.poll(() => createCount).toBe(1);
      await expect.poll(() => memberRequests).toHaveLength(1);
      expect(memberRequests[0].email).toBe("member2@example.com");
    });
  });

  test.describe("Edit Team", () => {
    test("edits team basic info", async ({ page }) => {
      let patchCount = 0;
      let currentTeam: Team = { ...MOCK_TEAM };

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [currentTeam] }),
        });
      });

      await page.route(MOCK_TEAM_ROUTE, async (route) => {
        if (route.request().method() === "PUT") {
          patchCount++;
          currentTeam = {
            ...currentTeam,
            name: "Engineering Updated",
            description: "Updated description",
            visibility: "public",
            max_members: 100,
          };
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(currentTeam),
          });
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();

      await expect(page.getByRole("heading", { name: "Edit Team" })).toBeVisible();

      await page.locator("#team-name").clear();
      await page.locator("#team-name").fill("Engineering Updated");
      await page.getByRole("textbox", { name: "Description" }).clear();
      await page.getByRole("textbox", { name: "Description" }).fill("Updated description");
      await page.getByText("Public", { exact: true }).click();
      await selectRadixOption(page, page.locator("#max-members"), "100");

      await page.getByRole("button", { name: "Save Changes" }).click();

      await expect.poll(() => patchCount).toBe(1);
      await expect(page.getByRole("heading", { name: "Teams" })).toBeVisible();
      await expect(page.getByText("Engineering Updated")).toBeVisible();
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /updated successfully/ }),
      ).toBeVisible();
    });

    test("edit form pre-populates values", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();

      await expect(page.locator("#team-name")).toHaveValue("Engineering");
      await expect(page.getByRole("textbox", { name: "Description" })).toHaveValue(
        "Core engineering team",
      );
      await expect(page.getByRole("radio", { name: "Private" })).toBeChecked();
      await expect(page.locator("#max-members")).toHaveText("50");
    });

    test("edit form does not show member management", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();

      await expect(page.getByRole("button", { name: "Add team member" })).not.toBeVisible();
      await expect(page.locator(TEAM_FORM_MEMBER_INPUT)).not.toBeVisible();
    });
  });

  test.describe("Manage Members", () => {
    test("opens dialog with existing members", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_MEMBER, MOCK_MEMBER_2]),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(
        dialog.locator(`${MANAGE_MEMBERS_INPUT}[value="john@example.com"]`),
      ).toBeVisible();
      await expect(
        dialog.locator(`${MANAGE_MEMBERS_INPUT}[value="jane@example.com"]`),
      ).toBeVisible();
      await expect(dialog.getByText("member", { exact: true })).toBeVisible();
      await expect(dialog.getByText("owner", { exact: true })).toBeVisible();
    });

    test("adds new member", async ({ page }) => {
      let postCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([MOCK_MEMBER]),
          });
        } else if (route.request().method() === "POST") {
          postCount++;
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              user_email: "newmember@example.com",
              role: "member",
              joined_at: new Date().toISOString(),
              invited_by: "test@example.com",
            } satisfies TeamMember),
          });
        }
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [{ email: "newmember@example.com", full_name: "New Member" }],
          }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      await page.getByRole("button", { name: "Add member" }).click();
      await pickComboboxOption(
        page,
        page.locator(MANAGE_MEMBERS_INPUT).last(),
        "newmember",
        "newmember@example.com",
      );

      await page.getByRole("button", { name: "Save" }).click();

      await expect.poll(() => postCount).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /member change/i }),
      ).toBeVisible();
    });

    test("removes member", async ({ page }) => {
      let deleteCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_MEMBER, MOCK_MEMBER_2]),
        });
      });

      await page.route(
        `${MOCK_TEAM_MEMBERS_ROUTE}/${encodeURIComponent(MOCK_MEMBER.user_email)}`,
        async (route) => {
          if (route.request().method() === "DELETE") {
            deleteCount++;
            await route.fulfill({ status: 204 });
          }
        },
      );

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      await page.getByRole("button", { name: "Remove john@example.com" }).click();
      await page.getByRole("button", { name: "Save" }).click();

      await expect.poll(() => deleteCount).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /member change/i }),
      ).toBeVisible();
    });

    test("changes member role", async ({ page }) => {
      let patchCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_MEMBER]),
        });
      });

      await page.route(
        `${MOCK_TEAM_MEMBERS_ROUTE}/${encodeURIComponent(MOCK_MEMBER.user_email)}`,
        async (route) => {
          if (route.request().method() === "PUT") {
            patchCount++;
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({ ...MOCK_MEMBER, role: "owner" }),
            });
          }
        },
      );

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      await selectRadixOption(page, page.locator('[data-slot="select-trigger"]').first(), "owner");
      await page.getByRole("button", { name: "Save" }).click();

      await expect.poll(() => patchCount).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /member change/i }),
      ).toBeVisible();
    });

    test("adds multiple members at once", async ({ page }) => {
      let postCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([]),
          });
        } else if (route.request().method() === "POST") {
          postCount++;
          const body = JSON.parse(route.request().postData() || "{}");
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              user_email: body.email,
              role: body.role,
              joined_at: new Date().toISOString(),
              invited_by: "test@example.com",
            } satisfies TeamMember),
          });
        }
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [
              { email: "member1@example.com", full_name: "Member One" },
              { email: "member2@example.com", full_name: "Member Two" },
              { email: "member3@example.com", full_name: "Member Three" },
            ],
          }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      // Dialog already shows one empty row (no existing members); add two more.
      await page.getByRole("button", { name: "Add member" }).click();
      await page.getByRole("button", { name: "Add member" }).click();

      await pickComboboxOption(
        page,
        page.locator(MANAGE_MEMBERS_INPUT).nth(0),
        "member1",
        "member1@example.com",
      );
      await pickComboboxOption(
        page,
        page.locator(MANAGE_MEMBERS_INPUT).nth(1),
        "member2",
        "member2@example.com",
      );
      await pickComboboxOption(
        page,
        page.locator(MANAGE_MEMBERS_INPUT).nth(2),
        "member3",
        "member3@example.com",
      );

      await page.getByRole("button", { name: "Save" }).click();

      await expect.poll(() => postCount).toBe(3);
    });

    test("existing member email is disabled", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_MEMBER]),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      const emailInput = page.locator(`${MANAGE_MEMBERS_INPUT}[value="john@example.com"]`);
      await expect(emailInput).toBeDisabled();

      const roleTrigger = page.locator('[data-slot="select-trigger"]').first();
      await expect(roleTrigger).toBeEnabled();
    });

    test("cancels without saving", async ({ page }) => {
      let apiCallCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify([MOCK_MEMBER]),
          });
        } else {
          apiCallCount++;
          await route.fulfill({ status: 200 });
        }
      });

      await page.route("**/auth/email/admin/users?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            users: [{ email: "newmember@example.com", full_name: "New Member" }],
          }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      await page.getByRole("button", { name: "Add member" }).click();
      await pickComboboxOption(
        page,
        page.locator(MANAGE_MEMBERS_INPUT).last(),
        "newmember",
        "newmember@example.com",
      );

      await page.getByRole("button", { name: "Cancel" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).not.toBeVisible();
      expect(apiCallCount).toBe(0);
    });
  });

  test.describe("Delete Team", () => {
    test("optimistically deletes team", async ({ page }) => {
      let deleteCount = 0;
      let teams: Team[] = [MOCK_TEAM, MOCK_TEAM_PUBLIC];

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams }),
        });
      });

      await page.route(MOCK_TEAM_ROUTE, async (route) => {
        if (route.request().method() === "DELETE") {
          deleteCount++;
          teams = teams.filter((t) => t.id !== MOCK_TEAM.id);
          await route.fulfill({ status: 204 });
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Engineering")).toBeVisible();
      await expect(page.getByText("Public Team")).toBeVisible();

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      await dialog.getByRole("button", { name: "Delete", exact: true }).click();

      const main = page.getByRole("main");
      await expect(dialog).not.toBeVisible();
      await expect(main.getByText("Engineering")).not.toBeVisible();
      await expect(main.getByText("Public Team")).toBeVisible();

      await expect.poll(() => deleteCount).toBe(1);
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /deleted successfully/ }),
      ).toBeVisible();
    });

    test("cancels delete dialog", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).not.toBeVisible();

      await expect(page.getByText("Engineering")).toBeVisible();
    });

    test("rolls back on API failure", async ({ page }) => {
      let deleteCount = 0;

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM, MOCK_TEAM_PUBLIC] }),
        });
      });

      await page.route(MOCK_TEAM_ROUTE, async (route) => {
        if (route.request().method() === "DELETE") {
          deleteCount++;
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Internal Server Error" }),
          });
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await expect(page.getByText("Engineering")).toBeVisible();

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "Delete", exact: true }).click();

      await expect(dialog).not.toBeVisible();

      await expect.poll(() => deleteCount).toBe(1);
      await expect(page.getByText("Engineering")).toBeVisible();
      await expect(
        page.locator("[data-sonner-toast]").filter({ hasText: /Failed to delete team/ }),
      ).toBeVisible();
    });

    test("shows confirmation with team name", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Delete" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(/Engineering/)).toBeVisible();
      await expect(dialog.getByText(/cannot be undone/i)).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();
    });
  });

  test.describe("Error Handling", () => {
    test("handles create API error", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          await route.fulfill({
            status: 400,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Team name already exists" }),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();
      await page.locator("#team-name").fill("Duplicate Team");
      await page.getByRole("button", { name: "Create Team" }).click();

      // Create/edit failures surface as an inline form alert, not a toast.
      await expect(page.getByRole("alert")).toHaveText(/Team name already exists/);
      await expect(page.getByRole("heading", { name: "Create Team" })).toBeVisible();
    });

    test("handles edit API error", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [MOCK_TEAM] }),
        });
      });

      await page.route(MOCK_TEAM_ROUTE, async (route) => {
        if (route.request().method() === "PUT") {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Internal Server Error" }),
          });
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();

      await page.locator("#team-name").clear();
      await page.locator("#team-name").fill("Updated Name");
      await page.getByRole("button", { name: "Save Changes" }).click();

      // A 500 is sanitized to a generic, non-leaky message shown inline in the form.
      await expect(page.getByRole("alert")).toHaveText(/Server error/i);
      await expect(page.getByRole("heading", { name: "Edit Team" })).toBeVisible();
    });

    test("shows loading states during operations", async ({ page }) => {
      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [] }),
        });
      });

      await page.route("**/teams", async (route) => {
        if (route.request().method() === "POST") {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              id: "team-new",
              name: "Slow Team",
              slug: "slow-team",
              created_by: "test@example.com",
              is_personal: false,
              visibility: "private",
              member_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              is_active: true,
            } satisfies Team),
          });
        } else {
          await route.fallback();
        }
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Create Team" }).click();
      await page.locator("#team-name").fill("Slow Team");

      // The header trigger is gone once the form is open (TeamForm replaces it in place),
      // so this is unambiguous at click time; re-querying by "Create Team" afterwards
      // wouldn't be, since the button's own label flips to "Creating...".
      await page.getByRole("button", { name: "Create Team" }).click();

      const creatingButton = page.getByRole("button", { name: /creating/i });
      await expect(creatingButton).toBeVisible();
      await expect(creatingButton).toBeDisabled();
    });
  });

  test.describe("Edge Cases", () => {
    test("handles long team name", async ({ page }) => {
      const longName = "A".repeat(150);
      const teamWithLongName: Team = { ...MOCK_TEAM, name: longName };

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [teamWithLongName] }),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      // aria-labels on the row's action buttons also contain the long name, so
      // scope to visible text (getByText) rather than accessible name (getByRole)
      // to avoid matching both the name cell and the actions cell.
      await expect(page.getByText(longName.substring(0, 50))).toBeVisible();

      await page.getByRole("button", { name: `Actions for ${longName.substring(0, 20)}` }).click();
      await page.getByRole("menuitem", { name: "Edit" }).click();

      await expect(page.locator("#team-name")).toHaveValue(longName);
    });

    test("handles team at max members", async ({ page }) => {
      const fullTeam: Team = { ...MOCK_TEAM, member_count: 50, max_members: 50 };

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [fullTeam] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_MEMBER]),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      // The dialog has no capacity gating today; it should still open cleanly
      // and let an admin manage members of a team that is at its cap.
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await expect(
        dialog.locator(`${MANAGE_MEMBERS_INPUT}[value="john@example.com"]`),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Add member" })).toBeEnabled();
    });

    test("handles team with zero members", async ({ page }) => {
      const emptyTeam: Team = { ...MOCK_TEAM, member_count: 0 };

      await page.route("**/teams?*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ teams: [emptyTeam] }),
        });
      });

      await page.route(MOCK_TEAM_MEMBERS_ROUTE, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      await page.goto(APP.TEAMS);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Actions for Engineering" }).click();
      await page.getByRole("menuitem", { name: "Manage Members" }).click();

      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();

      // With no existing members, the dialog seeds one blank, editable row.
      const emailInputs = page.locator(MANAGE_MEMBERS_INPUT);
      await expect(emailInputs).toHaveCount(1);
      await expect(emailInputs.first()).toBeEnabled();
      await expect(emailInputs.first()).toHaveValue("");
      await expect(page.getByRole("button", { name: "Add member" })).toBeEnabled();
    });
  });
});
