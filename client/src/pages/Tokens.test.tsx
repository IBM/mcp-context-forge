import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/test-utils";
import { Tokens } from "./Tokens";
import type { TokenResponse } from "@/types/token";

// Toasts are UI notifications, not network — mock the lib so we can assert on them.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";

const TEAMS = { teams: [{ id: "team-1", name: "devteam" }] };
const CATALOG = {
  all_permissions: ["tools.read", "tools.execute", "tools.create"],
  permissions_by_resource: {},
  total_count: 3,
};

function makeToken(overrides: Partial<TokenResponse> = {}): TokenResponse {
  return {
    id: "tok-1",
    name: "CI token",
    description: "used by ci",
    user_email: "dev@example.com",
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

/** Registers the read handlers the page (and create form) depend on. */
function primeHandlers(tokens: TokenResponse[]) {
  server.use(
    http.get("*/tokens", () =>
      HttpResponse.json({ tokens, total: tokens.length, limit: 0, offset: 0 }),
    ),
    http.get("*/teams", () => HttpResponse.json(TEAMS)),
    http.get("*/rbac/permissions/available", () => HttpResponse.json(CATALOG)),
    http.get("*/rbac/my/permissions", () => HttpResponse.json(["*"])),
  );
}

describe("Tokens page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state while the token list is fetching", async () => {
    server.use(
      http.get("*/tokens", async () => {
        await delay("infinite");
        return HttpResponse.json({ tokens: [], total: 0, limit: 0, offset: 0 });
      }),
      http.get("*/teams", () => HttpResponse.json(TEAMS)),
    );
    renderWithProviders(<Tokens />);
    expect(await screen.findByText("Loading API tokens")).toBeInTheDocument();
  });

  it("shows an error state when the list fails to load", async () => {
    server.use(
      http.get("*/tokens", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
      http.get("*/teams", () => HttpResponse.json(TEAMS)),
    );
    renderWithProviders(<Tokens />);
    expect(await screen.findByText("Failed to load API tokens")).toBeInTheDocument();
  });

  it("shows the empty state with a generate action when there are no tokens", async () => {
    primeHandlers([]);
    renderWithProviders(<Tokens />);
    expect(await screen.findByRole("heading", { name: "Generate API token" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate token" })).toBeInTheDocument();
  });

  it("lists tokens with their team name (read)", async () => {
    // One fully-populated token and one minimal token (no team / expiry /
    // description) to exercise the table's fallback rendering.
    primeHandlers([
      makeToken(),
      makeToken({
        id: "tok-2",
        name: "minimal",
        team_id: null,
        description: null,
        expires_at: null,
      }),
      // team_id present but not in the /teams map -> falls back to the raw id.
      makeToken({ id: "tok-3", name: "orphan", team_id: "ghost-team", description: null }),
    ]);
    renderWithProviders(<Tokens />);
    expect(await screen.findByText("CI token")).toBeInTheDocument();
    // team_id -> team name mapping from the /teams query
    expect(screen.getByText("devteam")).toBeInTheDocument();
    // Minimal token: no team ("—") and a "Never" expiry.
    expect(screen.getByText("minimal")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getAllByText("Never").length).toBeGreaterThan(0);
    // Unknown team id renders verbatim.
    expect(screen.getByText("ghost-team")).toBeInTheDocument();
  });

  it("opens the create form from the populated-list toolbar", async () => {
    const user = userEvent.setup();
    primeHandlers([makeToken()]);
    renderWithProviders(<Tokens />);

    // With tokens present, the generate action lives in the tab-row toolbar.
    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    expect(screen.getByPlaceholderText("Add a memorable name")).toBeInTheDocument();
  });

  it("creates a token and reveals the one-time secret (create)", async () => {
    const user = userEvent.setup();
    let posted: unknown;
    primeHandlers([]);
    server.use(
      http.post("*/tokens", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(
          {
            access_token: "eyJ-raw-secret",
            token: makeToken({ id: "tok-new", name: "new token" }),
          },
          { status: 201 },
        );
      }),
    );
    renderWithProviders(<Tokens />);

    // Empty state -> open the create form.
    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.type(screen.getByPlaceholderText("Add a memorable name"), "new token");
    await user.click(screen.getByRole("button", { name: "Generate token" }));

    await waitFor(() =>
      expect(posted).toMatchObject({
        name: "new token",
        expires_in_days: 30,
        team_id: "team-1",
      }),
    );
    expect(
      await screen.findByText("Save token in a secure place. It won't be viewable again."),
    ).toBeInTheDocument();
    expect(screen.getByText("eyJ-raw-secret")).toBeInTheDocument();

    // Copy the secret, then close the one-time dialog via the footer button
    // (the dialog also has a built-in X close, so pick the text-only one).
    await user.click(screen.getByRole("button", { name: "Copy API token" }));
    const footerClose = screen
      .getAllByRole("button", { name: "Close" })
      .find((button) => !button.querySelector("svg"));
    await user.click(footerClose!);
    await waitFor(() =>
      expect(
        screen.queryByText("Save token in a secure place. It won't be viewable again."),
      ).not.toBeInTheDocument(),
    );
  });

  it("submits advanced rate-limit and day restrictions", async () => {
    const user = userEvent.setup();
    let posted: { scope?: Record<string, unknown> } | undefined;
    primeHandlers([]);
    server.use(
      http.post("*/tokens", async ({ request }) => {
        posted = (await request.json()) as { scope?: Record<string, unknown> };
        return HttpResponse.json(
          { access_token: "raw", token: makeToken({ id: "tok-adv" }) },
          { status: 201 },
        );
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.type(screen.getByPlaceholderText("Add a memorable name"), "scoped token");
    await user.click(screen.getByRole("button", { name: "Advanced settings" }));
    await user.type(screen.getByPlaceholderText("Scope token to a server..."), "srv-1");
    await user.type(screen.getByPlaceholderText("192.168.1.0/24"), "10.0.0.0/8");
    await user.type(screen.getByPlaceholderText("e.g. 500"), "500");

    // Allowed-hours window (Start / End / Timezone selects).
    await user.click(screen.getByRole("combobox", { name: /Start/ }));
    await user.click(await screen.findByRole("option", { name: "08:00" }));
    await user.click(screen.getByRole("combobox", { name: /End/ }));
    await user.click(await screen.findByRole("option", { name: "17:00" }));
    await user.click(screen.getByRole("combobox", { name: /Timezone/ }));
    await user.click(await screen.findByRole("option", { name: /Coordinated Universal Time/ }));

    await user.click(screen.getByRole("checkbox", { name: "Sunday" })); // uncheck one day
    await user.click(screen.getByRole("button", { name: "Generate token" }));

    await waitFor(() => expect(posted).toBeDefined());
    expect(posted?.scope).toMatchObject({
      server_id: "srv-1",
      ip_restrictions: ["10.0.0.0/8"],
      usage_limits: { requests_per_hour: 500 },
      time_restrictions: { start_time: "08:00", end_time: "17:00", timezone: "UTC" },
    });
    const days = (posted?.scope?.time_restrictions as { days?: string[] })?.days ?? [];
    expect(days).toHaveLength(6);
    expect(days).not.toContain("Sunday");
  });

  it("requires at least one permission in 'only selected' mode", async () => {
    const user = userEvent.setup();
    let posted = false;
    primeHandlers([]);
    server.use(
      http.post("*/tokens", () => {
        posted = true;
        return HttpResponse.json({ access_token: "raw", token: makeToken() }, { status: 201 });
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.type(screen.getByPlaceholderText("Add a memorable name"), "unscoped");
    await user.click(screen.getByRole("radio", { name: "Only selected permissions" }));
    await screen.findByText("tools.read");
    await user.click(screen.getByRole("button", { name: "Generate token" }));

    expect(await screen.findByText("Select at least one permission")).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it("submits only the selected permission bucket scopes", async () => {
    const user = userEvent.setup();
    let posted: { scope?: { permissions?: string[] } } | undefined;
    primeHandlers([]);
    server.use(
      http.post("*/tokens", async ({ request }) => {
        posted = (await request.json()) as { scope?: { permissions?: string[] } };
        return HttpResponse.json(
          { access_token: "raw", token: makeToken({ id: "tok-scoped" }) },
          { status: 201 },
        );
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.type(screen.getByPlaceholderText("Add a memorable name"), "read only");
    await user.click(screen.getByRole("radio", { name: "Only selected permissions" }));
    await user.click(await screen.findByText("Read"));
    await user.click(screen.getByRole("button", { name: "Generate token" }));

    await waitFor(() => expect(posted).toBeDefined());
    expect(posted?.scope?.permissions).toEqual(["tools.read"]);
  });

  it("renders the permission buckets when 'only selected' is chosen", async () => {
    const user = userEvent.setup();
    primeHandlers([]);
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.click(screen.getByRole("radio", { name: "Only selected permissions" }));

    // Catalog scopes surface as chips, driven by the permission catalog + "*".
    expect(await screen.findByText("tools.read")).toBeInTheDocument();
    expect(screen.getByText("tools.execute")).toBeInTheDocument();
    expect(screen.getByText("tools.create")).toBeInTheDocument();
  });

  it("reveals the advanced settings fields", async () => {
    const user = userEvent.setup();
    primeHandlers([]);
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.click(screen.getByRole("button", { name: "Advanced settings" }));

    expect(screen.getByText("Server ID")).toBeInTheDocument();
    expect(screen.getByText("Rate limits")).toBeInTheDocument();
    expect(screen.getByText("Allowed days")).toBeInTheDocument();
  });

  it("deletes a token after confirmation (delete)", async () => {
    const user = userEvent.setup();
    let deletedId = "";
    primeHandlers([makeToken()]);
    server.use(
      http.delete("*/tokens/:id", ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Actions for CI token" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deletedId).toBe("tok-1"));
    expect(toast.success).toHaveBeenCalled();
  });

  it("surfaces an error toast when deletion fails", async () => {
    const user = userEvent.setup();
    primeHandlers([makeToken()]);
    server.use(
      http.delete("*/tokens/:id", () => HttpResponse.json({ detail: "nope" }, { status: 500 })),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Actions for CI token" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("cancels deletion without calling the API", async () => {
    const user = userEvent.setup();
    let deleted = false;
    primeHandlers([makeToken()]);
    server.use(
      http.delete("*/tokens/:id", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Actions for CI token" }));
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(deleted).toBe(false);
  });

  it("lets a multi-team user choose the team the token is scoped to", async () => {
    const user = userEvent.setup();
    let posted: { team_id?: string } | undefined;
    server.use(
      http.get("*/tokens", () => HttpResponse.json({ tokens: [], total: 0, limit: 0, offset: 0 })),
      http.get("*/teams", () =>
        HttpResponse.json({
          teams: [
            { id: "team-1", name: "devteam" },
            { id: "team-2", name: "ops" },
          ],
        }),
      ),
      http.post("*/tokens", async ({ request }) => {
        posted = (await request.json()) as { team_id?: string };
        return HttpResponse.json(
          { access_token: "raw", token: makeToken({ id: "tok-team" }) },
          { status: 201 },
        );
      }),
    );
    renderWithProviders(<Tokens />);

    await user.click(await screen.findByRole("button", { name: "Generate token" }));
    await user.type(screen.getByPlaceholderText("Add a memorable name"), "ops token");
    // The selector appears only for multi-team users; switch to the second team.
    await user.click(screen.getByRole("combobox", { name: /Team/ }));
    await user.click(await screen.findByRole("option", { name: "ops" }));
    await user.click(screen.getByRole("button", { name: "Generate token" }));

    await waitFor(() => expect(posted?.team_id).toBe("team-2"));
  });
});
