import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: () => ({
    user: {
      email: "test@example.com",
      full_name: "Test User",
      is_admin: true,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    },
    isAuthenticated: true,
    isLoading: false,
    selectedTeamId: null,
    login: vi.fn(),
    logout: vi.fn(),
    setSelectedTeamId: vi.fn(),
  }),
}));

import { toast } from "sonner";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { Resources } from "./Resources";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import type { ReactElement } from "react";
import type { ResourceRead } from "@/generated/types";

type Resource = NonNullable<ResourceRead>;

// Helper: create mock resource. `gatewayId` doubles as the group label shown
// in the UI — it's never resolved against a real gateway record in these
// tests, so buildGroups() falls back to using it verbatim as the slug.
function createMockResource(id: number, gatewayId: string | null, enabled = true): Resource {
  return {
    id: `resource-${id}`,
    name: `Resource ${id}`,
    description: `Description for resource ${id}`,
    gatewayId: gatewayId || null,
    enabled,
    uri: `resource://example/${id}`,
    mimeType: "application/json",
    size: 0,
    version: 1,
    visibility: "public",
    tags: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

// Helper: render with router + auth
function renderWithRouter(ui: ReactElement) {
  window.history.pushState({}, "", "/app/resources");

  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("Resources", () => {
  beforeEach(() => {
    server.resetHandlers();
    // Mock window.confirm for delete operations
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders loading state initially", async () => {
    let resolveRequest: () => void;
    const requestGate = new Promise<void>((resolve) => {
      resolveRequest = resolve;
    });

    server.use(
      http.get("/resources", async () => {
        await requestGate;
        return HttpResponse.json([]);
      }),
    );

    renderWithRouter(<Resources />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading resources, please wait...")).toBeInTheDocument();

    resolveRequest!();
    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });
  });

  it("renders Add resources card", async () => {
    server.use(http.get("/resources", () => HttpResponse.json([])));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Resources will appear automatically when you connect a MCP server/i),
    ).toBeInTheDocument();
  });

  it("handles Add resources card click", async () => {
    const user = userEvent.setup();
    server.use(http.get("/resources", () => HttpResponse.json([])));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const addCard = screen.getByText("Add resources").closest('[data-slot="card"]');
    expect(addCard).toBeInTheDocument();

    await user.click(addCard!);

    // Form should open
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add resources" })).toBeInTheDocument();
    });
  });

  it("handles Add resources card keyboard activation", async () => {
    const user = userEvent.setup();
    server.use(http.get("/resources", () => HttpResponse.json([])));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const addCard = screen.getByRole("button");
    expect(addCard).toHaveAttribute("tabindex", "0");

    addCard.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add resources" })).toBeInTheDocument();
    });
  });

  it("displays error message when API call fails", async () => {
    server.use(
      http.get("/resources", () => {
        return HttpResponse.json({ detail: "Failed to fetch resources" }, { status: 500 });
      }),
    );

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading resources")).toBeInTheDocument();
  });

  it("groups resources by gateway slug correctly", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "gateway-a"),
      createMockResource(2, "gateway-a"),
      createMockResource(3, "gateway-a"),
      createMockResource(4, "gateway-b"),
      createMockResource(5, "gateway-b"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-a")).toBeInTheDocument();
    });

    expect(screen.getByText("gateway-b")).toBeInTheDocument();
    expect(screen.getByText("3 resources")).toBeInTheDocument();
    expect(screen.getByText("2 resources")).toBeInTheDocument();
  });

  it("groups resources without a gateway into the REST resources bucket", async () => {
    const mockResources: Resource[] = [createMockResource(1, null)];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("REST resources")).toBeInTheDocument();
    });

    expect(screen.getByText("1 resource")).toBeInTheDocument();
  });

  it("correctly pluralizes resource count", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "single-resource-gateway"),
      createMockResource(2, "multi-resource-gateway"),
      createMockResource(3, "multi-resource-gateway"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("1 resource")).toBeInTheDocument();
    });

    expect(screen.getByText("2 resources")).toBeInTheDocument();
  });

  it("shows active status indicator for groups with at least one enabled resource", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "active-gateway", true),
      createMockResource(2, "inactive-gateway", false),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("active-gateway")).toBeInTheDocument();
    });

    expect(screen.getByText("inactive-gateway")).toBeInTheDocument();

    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(3);
  });

  it("displays resource descriptions as tooltips", async () => {
    const mockResources: Resource[] = [createMockResource(1, "server-1")];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    const resourceBadge = screen.getByText("Resource 1");
    expect(resourceBadge).toHaveAttribute("title", "Description for resource 1");
  });

  it("renders more options button for each resource group", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "server-1"),
      createMockResource(2, "server-2"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("server-1")).toBeInTheDocument();
    });

    const moreOptionsButtons = screen.getAllByLabelText(/More options for/i);
    expect(moreOptionsButtons).toHaveLength(2);
    expect(screen.getByLabelText("More options for server-1")).toBeInTheDocument();
    expect(screen.getByLabelText("More options for server-2")).toBeInTheDocument();
  });

  it("handles empty resources list", async () => {
    server.use(http.get("/resources", () => HttpResponse.json([])));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(1);
  });

  it("uses correct grid layout classes", async () => {
    server.use(http.get("/resources", () => HttpResponse.json([])));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const gridContainer = screen
      .getByText("Add resources")
      .closest('[data-slot="card"]')?.parentElement;

    expect(gridContainer).toBeInTheDocument();
    expect(gridContainer).toHaveClass("grid");
    expect(gridContainer).toHaveClass("grid-cols-1");
    expect(gridContainer).toHaveClass("lg:grid-cols-2");
    expect(gridContainer).toHaveClass("2xl:grid-cols-3");
  });

  it("handles network errors gracefully", async () => {
    server.use(
      http.get("/resources", () => {
        return HttpResponse.error();
      }),
    );

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    expect(screen.getByText("Error loading resources")).toBeInTheDocument();
  });

  it("displays up to 8 resources and shows +N tag for remaining resources", async () => {
    const mockResources: Resource[] = Array.from({ length: 12 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-many-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-many-resources")).toBeInTheDocument();
    });

    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 8")).toBeInTheDocument();

    expect(screen.queryByText("Resource 9")).not.toBeInTheDocument();
    expect(screen.queryByText("Resource 12")).not.toBeInTheDocument();

    expect(screen.getByText("+4")).toBeInTheDocument();
    expect(screen.getByTitle("4 more resources")).toBeInTheDocument();
  });

  it("displays all resources when count is 8 or less without +N tag", async () => {
    const mockResources: Resource[] = Array.from({ length: 8 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-eight-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-eight-resources")).toBeInTheDocument();
    });

    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 8")).toBeInTheDocument();

    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });

  it("shows +1 tag with singular 'resource' in title for 9 resources", async () => {
    const mockResources: Resource[] = Array.from({ length: 9 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-nine-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-nine-resources")).toBeInTheDocument();
    });

    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByTitle("1 more resource")).toBeInTheDocument();
  });

  describe("Dropdown Menu and Details Panel", () => {
    it("opens dropdown menu when clicking more options button", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);

      await waitFor(() => {
        expect(screen.getByText("View Details")).toBeInTheDocument();
      });
    });

    it("opens details panel when clicking View Details menu item", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [
        createMockResource(1, "test-gateway"),
        createMockResource(2, "test-gateway"),
      ];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);

      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for test-gateway/i }),
        ).toBeInTheDocument();
      });

      expect(screen.getAllByText("test-gateway").length).toBeGreaterThan(0);
    });

    it("closes details panel when clicking close button", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for test-gateway/i }),
        ).toBeInTheDocument();
      });

      const closeButton = screen.getByLabelText("Close resource details");
      await user.click(closeButton);

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Resources for test-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("closes details panel when pressing Escape key", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for test-gateway/i }),
        ).toBeInTheDocument();
      });

      await user.keyboard("{Escape}");

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Resources for test-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("displays all resources from selected group in details panel", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [
        createMockResource(1, "multi-resource-gateway"),
        createMockResource(2, "multi-resource-gateway"),
        createMockResource(3, "multi-resource-gateway"),
      ];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("multi-resource-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for multi-resource-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for multi-resource-gateway/i }),
        ).toBeInTheDocument();
      });

      const panel = screen.getByRole("region", { name: /Resources for multi-resource-gateway/i });
      expect(within(panel).getAllByText("Resource 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Resource 2").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Resource 3").length).toBeGreaterThan(0);
    });

    it("handles opening details panel for different resource groups", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [
        createMockResource(1, "gateway-a"),
        createMockResource(2, "gateway-b"),
      ];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("gateway-a")).toBeInTheDocument();
      });

      const moreOptionsButtonA = screen.getByLabelText("More options for gateway-a");
      await user.click(moreOptionsButtonA);
      let viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for gateway-a/i }),
        ).toBeInTheDocument();
      });

      const closeButton = screen.getByLabelText("Close resource details");
      await user.click(closeButton);

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Resources for gateway-a/i }),
        ).not.toBeInTheDocument();
      });

      const moreOptionsButtonB = screen.getByLabelText("More options for gateway-b");
      await user.click(moreOptionsButtonB);
      viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for gateway-b/i }),
        ).toBeInTheDocument();
      });
    });
  });

  describe("Add resource form", () => {
    async function openAndFillForm(user: ReturnType<typeof userEvent.setup>) {
      await waitFor(() => expect(screen.getByText("Add resources")).toBeInTheDocument());
      await user.click(screen.getByText("Add resources").closest('[data-slot="card"]')!);
      await waitFor(() =>
        expect(screen.getByRole("heading", { name: "Add resources" })).toBeInTheDocument(),
      );
      await user.type(screen.getByLabelText(/URI/i), "resource://example/new");
      await user.type(screen.getByLabelText(/Name/i), "New Resource");
      await user.type(screen.getByLabelText(/Content/i), "some content");
    }

    it("closes form and shows new resource group on success", async () => {
      const user = userEvent.setup();
      let refetchCount = 0;

      server.use(
        http.get("/resources", () => {
          refetchCount += 1;
          if (refetchCount === 1) return HttpResponse.json([]);
          return HttpResponse.json([createMockResource(99, "test-gw")]);
        }),
        http.get("/gateways", () =>
          HttpResponse.json({ gateways: [], next_cursor: null, total: 0 }),
        ),
        http.post("/resources", () => HttpResponse.json({ id: "res-99" }, { status: 201 })),
      );

      renderWithRouter(<Resources />);
      await openAndFillForm(user);

      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() =>
        expect(screen.queryByRole("heading", { name: "Add resources" })).not.toBeInTheDocument(),
      );
      await waitFor(() => expect(screen.getByText("Resource 99")).toBeInTheDocument());
    });

    it("shows submit error and keeps form open on API failure", async () => {
      const user = userEvent.setup();

      server.use(
        http.get("/resources", () => HttpResponse.json([])),
        http.get("/gateways", () =>
          HttpResponse.json({ gateways: [], next_cursor: null, total: 0 }),
        ),
        http.post("/resources", () =>
          HttpResponse.json({ detail: "URI already in use" }, { status: 409 }),
        ),
      );

      renderWithRouter(<Resources />);
      await openAndFillForm(user);

      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() =>
        expect(screen.getByRole("heading", { name: "Add resources" })).toBeInTheDocument(),
      );
      await waitFor(() => expect(screen.getByText("URI already in use")).toBeInTheDocument());
    });
  });

  describe("ResourceForm Toggle", () => {
    it("closes form when Cancel clicked", async () => {
      const user = userEvent.setup();
      server.use(http.get("/resources", () => HttpResponse.json([])));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Add resources")).toBeInTheDocument();
      });

      await user.click(screen.getByText("Add resources").closest('[data-slot="card"]')!);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Add resources" })).toBeInTheDocument();
      });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));

      await waitFor(() => {
        expect(screen.getByText("Add resources")).toBeInTheDocument();
      });
      expect(screen.queryByRole("heading", { name: "Add resources" })).not.toBeInTheDocument();
    });
  });

  describe("Optimistic delete", () => {
    async function setup(mockResources: Resource[], gatewaySlug: string) {
      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));
      renderWithRouter(<Resources />);
      await waitFor(() => expect(screen.getByText(gatewaySlug)).toBeInTheDocument());

      const user = userEvent.setup();
      await user.click(screen.getByLabelText(`More options for ${gatewaySlug}`));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(
          screen.getByRole("region", { name: new RegExp(`Resources for ${gatewaySlug}`, "i") }),
        ).toBeInTheDocument(),
      );
      return { user };
    }

    beforeEach(() => {
      vi.mocked(toast.success).mockClear();
      vi.mocked(toast.error).mockClear();
      server.resetHandlers();
    });

    it("removes the resource badge from the card grid immediately on confirm (before API responds)", async () => {
      const mockResources = [createMockResource(1, "opt-gateway")];

      let resolveDelete!: () => void;
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete(
          "/resources/resource-1",
          () =>
            new Promise<Response>((resolve) => {
              resolveDelete = () => resolve(new Response(null, { status: 204 }));
            }),
        ),
      );

      renderWithRouter(<Resources />);
      await waitFor(() => expect(screen.getByText("opt-gateway")).toBeInTheDocument());

      expect(screen.getByText("Resource 1")).toBeInTheDocument();

      const user = userEvent.setup();
      await user.click(screen.getByLabelText("More options for opt-gateway"));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(
          screen.getByRole("region", { name: /Resources for opt-gateway/i }),
        ).toBeInTheDocument(),
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(screen.queryByText("Resource 1")).not.toBeInTheDocument();
      });

      resolveDelete();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Resource 1"));
      });
    });

    it("rolls back: resource badge reappears in card grid when delete API fails", async () => {
      const mockResources = [createMockResource(1, "rollback-gateway")];
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete("/resources/resource-1", () =>
          HttpResponse.json({ detail: "Server error" }, { status: 500 }),
        ),
      );

      renderWithRouter(<Resources />);
      await waitFor(() => expect(screen.getByText("rollback-gateway")).toBeInTheDocument());

      const user = userEvent.setup();
      await user.click(screen.getByLabelText("More options for rollback-gateway"));
      await user.click(await screen.findByText("View Details"));
      await waitFor(() =>
        expect(
          screen.getByRole("region", { name: /Resources for rollback-gateway/i }),
        ).toBeInTheDocument(),
      );

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith("Server error");
      });

      await waitFor(() => {
        expect(screen.getByText("1 resource")).toBeInTheDocument();
      });
    });

    it("details panel closes immediately when the only resource in a group is deleted", async () => {
      const mockResources = [createMockResource(1, "solo-gateway")];
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete("/resources/resource-1", () => new HttpResponse(null, { status: 204 })),
      );

      const { user } = await setup(mockResources, "solo-gateway");

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.queryByRole("region", { name: /Resources for solo-gateway/i }),
        ).not.toBeInTheDocument();
      });
    });

    it("details panel stays open when one resource is deleted from a multi-resource group", async () => {
      const mockResources = [
        createMockResource(1, "multi-gateway"),
        createMockResource(2, "multi-gateway"),
      ];
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete("/resources/resource-1", () => new HttpResponse(null, { status: 204 })),
      );

      const { user } = await setup(mockResources, "multi-gateway");

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for multi-gateway/i }),
        ).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Resource 1"));
      });
    });

    it("deleted resource row is removed from panel immediately while remaining resource stays visible", async () => {
      const mockResources = [
        createMockResource(1, "panel-gateway"),
        createMockResource(2, "panel-gateway"),
      ];

      let resolveDelete!: () => void;
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete(
          "/resources/resource-1",
          () =>
            new Promise<Response>((resolve) => {
              resolveDelete = () => resolve(new Response(null, { status: 204 }));
            }),
        ),
      );

      const { user } = await setup(mockResources, "panel-gateway");

      const panel = screen.getByRole("region", { name: /Resources for panel-gateway/i });

      expect(within(panel).getAllByText("Resource 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Resource 2").length).toBeGreaterThan(0);

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(within(panel).queryByText("Resource 1")).not.toBeInTheDocument();
      });
      expect(within(panel).getAllByText("Resource 2").length).toBeGreaterThan(0);

      resolveDelete();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Resource 1"));
      });
    });

    it("details panel re-opens after rollback when group had multiple resources", async () => {
      const mockResources = [
        createMockResource(1, "reopen-gateway"),
        createMockResource(2, "reopen-gateway"),
      ];
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete("/resources/resource-1", () =>
          HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
        ),
      );

      const { user } = await setup(mockResources, "reopen-gateway");

      const moreOptionsButtons = screen.getAllByLabelText("More options");
      await user.click(moreOptionsButtons[0]);
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(
          screen.getByRole("region", { name: /Resources for reopen-gateway/i }),
        ).toBeInTheDocument();
      });

      const panel = screen.getByRole("region", { name: /Resources for reopen-gateway/i });
      expect(within(panel).getAllByText("Resource 1").length).toBeGreaterThan(0);
      expect(within(panel).getAllByText("Resource 2").length).toBeGreaterThan(0);

      expect(toast.error).toHaveBeenCalledWith("Forbidden");
    });

    it("shows generic error toast when delete returns no detail field", async () => {
      const mockResources = [createMockResource(1, "err-gateway")];
      server.use(
        http.get("/resources", () => HttpResponse.json(mockResources)),
        http.delete("/resources/resource-1", () =>
          HttpResponse.json({ message: "Unexpected error" }, { status: 500 }),
        ),
      );

      const { user } = await setup(mockResources, "err-gateway");

      await user.click(screen.getByLabelText("More options"));
      await user.click(await screen.findByText("Delete"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /^delete$/i }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          expect.stringContaining("Failed to delete resource"),
        );
      });
    });
  });

  describe("Error Boundary", () => {
    it("catches and displays rendering errors gracefully", async () => {
      const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      server.use(
        http.get("/resources", () => {
          throw new Error("Simulated rendering error");
        }),
      );

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      consoleErrorSpy.mockRestore();
    });
  });
});
