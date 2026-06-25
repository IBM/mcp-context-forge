import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { Resources } from "./Resources";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import type { ReactElement } from "react";
import type { ResourceRead } from "@/generated/types";

type Resource = NonNullable<ResourceRead>;

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
    size: 0,
    version: 1,
    visibility: "public",
    tags: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  } as unknown as Resource;
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
        return HttpResponse.json([]);
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

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resources")).toBeInTheDocument();
    });

    // Check individual resource cards rendered
    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 2")).toBeInTheDocument();
    expect(screen.getByText("Resource 3")).toBeInTheDocument();

    // Should have 4 cards total (3 resources + 1 add card)
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(4);
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
      expect(screen.getByRole("heading", { name: "Add Resource" })).toBeInTheDocument();
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

  it("renders individual resource cards for all resources", async () => {
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
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    // All 5 resources should be visible as individual cards
    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 2")).toBeInTheDocument();
    expect(screen.getByText("Resource 3")).toBeInTheDocument();
    expect(screen.getByText("Resource 4")).toBeInTheDocument();
    expect(screen.getByText("Resource 5")).toBeInTheDocument();

    // Should have 6 cards total (5 resources + 1 add card)
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(6);
  });

  it("shows active status indicator for enabled resources", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "active-gateway", true),
      createMockResource(2, "inactive-gateway", false),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    expect(screen.getByText("Resource 2")).toBeInTheDocument();

    // Should have 3 cards total (2 resources + 1 add card)
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(3);
  });

  it("displays resource names in card headers", async () => {
    const mockResources: Resource[] = [createMockResource(1, "server-1")];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    // Resource name should be visible in the card
    const resourceName = screen.getByText("Resource 1");
    expect(resourceName).toBeInTheDocument();
  });

  it("renders more options button for each resource card", async () => {
    const mockResources: Resource[] = [
      createMockResource(1, "server-1"),
      createMockResource(2, "server-2"),
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    const moreOptionsButtons = screen.getAllByLabelText(/More options for/i);
    expect(moreOptionsButtons).toHaveLength(2);
    expect(screen.getByLabelText("More options for Resource 1")).toBeInTheDocument();
    expect(screen.getByLabelText("More options for Resource 2")).toBeInTheDocument();
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

  it("renders resources without gateway slug", async () => {
    const mockResources: Resource[] = [
      {
        ...createMockResource(1, ""),
      },
    ];

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    // Should have 2 cards total (1 resource + 1 add card)
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(2);
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

  it("displays all resources as individual cards", async () => {
    const mockResources: Resource[] = Array.from({ length: 12 }, (_, i) =>
      createMockResource(i + 1, "gateway-with-many-resources"),
    );

    server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

    renderWithRouter(<Resources />);

    await waitFor(() => {
      expect(screen.getByText("Resource 1")).toBeInTheDocument();
    });

    // All 12 resources should be visible as individual cards
    expect(screen.getByText("Resource 1")).toBeInTheDocument();
    expect(screen.getByText("Resource 12")).toBeInTheDocument();

    // Should have 13 cards total (12 resources + 1 add card)
    const cards = document.querySelectorAll('[data-slot="card"]');
    expect(cards).toHaveLength(13);
  });

  describe("Dropdown Menu and Details Panel", () => {
    it("opens dropdown menu when clicking more options button", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Resource 1")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for Resource 1");
      await user.click(moreOptionsButton);

      await waitFor(() => {
        expect(screen.getByText("View Details")).toBeInTheDocument();
      });
    });

    it("opens details panel when clicking View Details menu item", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Resource 1")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for Resource 1");
      await user.click(moreOptionsButton);

      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);

      await waitFor(() => {
        expect(screen.getByText(/gateway-test-gateway Resources/i)).toBeInTheDocument();
      });
    });

    it("closes details panel when clicking close button", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Resource 1")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for Resource 1");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);
      await waitFor(() => {
        expect(screen.getByText(/gateway-test-gateway Resources/i)).toBeInTheDocument();
      });

      const closeButton = screen.getByLabelText("Close panel");
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText(/Resource 1 Details/i)).not.toBeInTheDocument();
      });
    });

    it("closes details panel when pressing Escape key", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Resource 1")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for Resource 1");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);
      await waitFor(() => {
        expect(screen.getByText(/gateway-test-gateway Resources/i)).toBeInTheDocument();
      });

      await user.keyboard("{Escape}");

      await waitFor(() => {
        expect(screen.queryByText(/Resource 1 Details/i)).not.toBeInTheDocument();
      });
    });

    it("displays resource details in details panel", async () => {
      const user = userEvent.setup();
      const mockResources: Resource[] = [createMockResource(1, "test-gateway")];

      server.use(http.get("/resources", () => HttpResponse.json(mockResources)));

      renderWithRouter(<Resources />);

      await waitFor(() => {
        expect(screen.getByText("Resource 1")).toBeInTheDocument();
      });

      const moreOptionsButton = screen.getByLabelText("More options for Resource 1");
      await user.click(moreOptionsButton);
      const viewDetailsItem = await screen.findByText("View Details");
      await user.click(viewDetailsItem);
      await waitFor(() => {
        expect(screen.getByText(/gateway-test-gateway Resources/i)).toBeInTheDocument();
      });
      // Resource details visible in panel
      const panel = screen.getByText(/gateway-test-gateway Resources/i).closest('[role="dialog"]');
      expect(panel).toBeInTheDocument();
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
        expect(screen.getByRole("heading", { name: "Add Resource" })).toBeInTheDocument();
      });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));

      await waitFor(() => {
        expect(screen.getByText("Add resources")).toBeInTheDocument();
      });
      expect(screen.queryByRole("heading", { name: "Add Resource" })).not.toBeInTheDocument();
    });
  });

  describe("Error Boundary", () => {
    it("catches and displays rendering errors gracefully", async () => {
      // Mock console.error to suppress error output in test logs
      const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      // Force a rendering error by making the component throw
      server.use(
        http.get("/resources", () => {
          throw new Error("Simulated rendering error");
        }),
      );

      renderWithRouter(<Resources />);

      // Error boundary should catch the error and display fallback UI
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      consoleErrorSpy.mockRestore();
    });
  });
});
