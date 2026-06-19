import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { Resources } from "./Resources";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import type { ReactElement } from "react";
import type { Resource } from "@/types/resource";

// Helper: create mock resource
function createMockResource(id: number, gatewaySlug: string, enabled = true): Resource {
  return {
    id: `resource-${id}`,
    name: `Resource ${id}`,
    description: `Description for resource ${id}`,
    gatewayId: `gateway-${gatewaySlug}`,
    gatewaySlug,
    enabled,
    uri: `resource://example/${id}`,
    mimeType: "application/json",
    tags: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

// Helper: render with router + auth
function renderWithRouter(ui: ReactElement) {
  window.history.pushState({}, "", "/app/resources");

  return render(
    <AuthProvider>
      <RouterProvider>
        <I18nProvider>{ui}</I18nProvider>
      </RouterProvider>
    </AuthProvider>,
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

  it("renders loading state initially", () => {
    server.use(
      http.get("/resources", async () => {
        await new Promise(() => {}); // Never resolves
        return HttpResponse.json({ data: [] });
      }),
    );

    renderWithRouter(<Resources />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading resources, please wait...")).toBeInTheDocument();
  });

  it("renders resources list when data loaded", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "server-1"),
      createMockResource(2, "server-1"),
      createMockResource(3, "server-2"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resources")).toBeInTheDocument();
    });

    // Check groups rendered
    expect(screen.getByText("server-1")).toBeInTheDocument();
    expect(screen.getByText("server-2")).toBeInTheDocument();

    // Check counts
    expect(screen.getByText("2 resources")).toBeInTheDocument();
    expect(screen.getByText("1 resource")).toBeInTheDocument();

    // Check individual resources
    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 2")).toBeInTheDocument();
    expect(screen.getByText("Resource 3")).toBeInTheDocument();
  });

  it("renders Add resources card", async () => {
    server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

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
    server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const addCard = screen.getByText("Add resources").closest('[data-slot="card"]');
    expect(addCard).toBeInTheDocument();

    await user.click(addCard!);

    // Form should open
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add Resource" })).toBeInTheDocument();
    });
  });

  it("handles Add resources card keyboard activation", async () => {
    const user = userEvent.setup();
    server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const addCard = screen.getByRole("button");
    expect(addCard).toHaveAttribute("tabindex", "0");

    addCard.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Add Resource" })).toBeInTheDocument();
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

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-a")).toBeInTheDocument();
    });

    expect(screen.getByText("gateway-b")).toBeInTheDocument();
    expect(screen.getByText("3 resources")).toBeInTheDocument();
    expect(screen.getByText("2 resources")).toBeInTheDocument();
  });

  it("shows active status indicator for enabled resources", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "active-gateway", true),
      createMockResource(2, "inactive-gateway", false),
    ];

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("active-gateway")).toBeInTheDocument();
    });

    expect(screen.getByText("inactive-gateway")).toBeInTheDocument();

    const cards = screen
      .getAllByRole("generic")
      .filter((el) => el.getAttribute("data-slot") === "card");
    expect(cards.length).toBeGreaterThan(0);
  });

  it("displays resource descriptions as tooltips", async () => {
    const mockResources: Resource[] = [createMockResource(1, "server-1")];

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

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

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

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
    server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Add resources")).toBeInTheDocument();
    });

    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(1);
  });

  it("uses correct grid layout classes", async () => {
    server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

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

  it("groups resources without gateway slug under 'ungrouped'", async () => {
    const mockResources: Resource[] = [
      {
        ...createMockResource(1, ""),
        gatewaySlug: "",
      },
    ];

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("ungrouped")).toBeInTheDocument();
    });

    expect(screen.getByText("1 resource")).toBeInTheDocument();
  });

  it("correctly pluralizes resource count", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "single-resource-gateway"),
      createMockResource(2, "multi-resource-gateway"),
      createMockResource(3, "multi-resource-gateway"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("1 resource")).toBeInTheDocument();
    });

    expect(screen.getByText("2 resources")).toBeInTheDocument();
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

  it("displays up to 8 resources and shows +N tag for remaining", async () => {
    const mockResources: Resource[] = Array.from({ length: 12 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-many-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("gateway-with-many-resources")).toBeInTheDocument();
    });

    // First 8 visible
    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 8")).toBeInTheDocument();

    // 9-12 not visible
    expect(screen.queryByText("Resource 9")).not.toBeInTheDocument();
    expect(screen.queryByText("Resource 12")).not.toBeInTheDocument();

    // +4 tag
    expect(screen.getByText("+4")).toBeInTheDocument();
    expect(screen.getByTitle("4 more resources")).toBeInTheDocument();
  });

  it("displays all resources when count is 8 or less without +N tag", async () => {
    const mockResources: Resource[] = Array.from({ length: 8 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-eight-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

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

    server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

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

      server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

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

      server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);

      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText(/test-gateway Resources/i)).toBeInTheDocument();
      });
    });

    it("closes details panel when clicking close button", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText(/test-gateway Resources/i)).toBeInTheDocument();
      });

      const closeButton = screen.getByLabelText("Close panel");
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText(/test-gateway Resources/i)).not.toBeInTheDocument();
      });
    });

    it("closes details panel when pressing Escape key", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("test-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for test-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText(/test-gateway Resources/i)).toBeInTheDocument();
      });

      await user.keyboard("{Escape}");

      await waitFor(() => {
        expect(screen.queryByText(/test-gateway Resources/i)).not.toBeInTheDocument();
      });
    });

    it("displays all resources from selected group in details panel", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [
        createMockResource(1, "multi-resource-gateway"),
        createMockResource(2, "multi-resource-gateway"),
        createMockResource(3, "multi-resource-gateway"),
      ];

      server.use(http.get("/resources", () => HttpResponse.json({ data: mockResources })));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("multi-resource-gateway")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for multi-resource-gateway");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText(/multi-resource-gateway Resources/i)).toBeInTheDocument();
      });

      // All resources visible in panel
      const panel = screen
        .getByText(/multi-resource-gateway Resources/i)
        .closest('[role="dialog"]');
      expect(panel).toBeInTheDocument();
      expect(within(panel! as HTMLElement).getAllByText(/Resource \d/)).toHaveLength(3);
    });
  });

  describe("ResourceForm Toggle", () => {
    it("closes form when Cancel clicked", async () => {
      const user = userEvent.setup();
      server.use(http.get("/resources", () => HttpResponse.json({ data: [] })));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Add resources")).toBeInTheDocument();
      });

      await user.click(screen.getByText("Add resources").closest('[data-slot="card"]')!);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Add Resource" })).toBeInTheDocument();
      });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));

      await waitFor(() => {
        expect(screen.getByText("Add resources")).toBeInTheDocument();
      });
      expect(screen.queryByRole("heading", { name: "Add Resource" })).not.toBeInTheDocument();
    });
  });
});
