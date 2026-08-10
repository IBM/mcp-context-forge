import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CatalogListResponse, CatalogServer } from "@/generated/types";
import { useQuery } from "@/hooks/useQuery";
import { I18nProvider } from "@/i18n";
import { RouterProvider } from "@/router";
import { ServerCatalog } from "./ServerCatalog";

vi.mock("@/hooks/useQuery", () => ({
  useQuery: vi.fn(),
}));

const mockUseQuery = vi.mocked(useQuery);

const openConnected: CatalogServer = {
  id: "open-connected",
  name: "Globalping",
  category: "Monitoring",
  url: "https://globalping.example/mcp",
  auth_type: "Open",
  provider: "jsDelivr",
  description: "Global network testing and monitoring",
  tags: ["network", "observability"],
  transport: "STREAMABLEHTTP",
  is_registered: true,
};

const openAvailable: CatalogServer = {
  id: "open-available",
  name: "Public Notes",
  category: "Productivity",
  url: "https://notes.example/mcp",
  auth_type: "Open",
  provider: "Example",
  description: "Search public notes and documents",
  tags: ["search", "documents"],
  is_registered: false,
};

const apiKeyServer: CatalogServer = {
  id: "api-key",
  name: "Secret Service",
  category: "Security",
  url: "https://secret.example/mcp",
  auth_type: "API Key",
  provider: "Example",
  description: "Requires a secret API key",
  tags: ["security"],
  is_registered: false,
};

const response: CatalogListResponse = {
  servers: [openConnected, openAvailable, apiKeyServer],
  total: 3,
  categories: ["Monitoring", "Productivity", "Security"],
  auth_types: ["API Key", "Open"],
  providers: ["Example", "jsDelivr"],
  all_tags: ["documents", "network", "observability", "search", "security"],
};

function queryResult(overrides: Partial<ReturnType<typeof useQuery>> = {}) {
  return {
    data: response,
    error: null,
    isLoading: false,
    execute: vi.fn(),
    refetch: vi.fn(),
    setData: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useQuery>;
}

function renderWithRouter(ui: ReactElement, path = "/app/server-catalog") {
  window.history.pushState({}, "", path);
  return render(
    <RouterProvider>
      <I18nProvider>{ui}</I18nProvider>
    </RouterProvider>,
  );
}

describe("ServerCatalog", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/app/");
    mockUseQuery.mockReturnValue(queryResult());
  });

  it("uses the catalog GET endpoint and shared loader", () => {
    mockUseQuery.mockReturnValue(queryResult({ data: undefined, isLoading: true }));

    renderWithRouter(<ServerCatalog />);

    expect(mockUseQuery).toHaveBeenCalledWith("/v1/catalog?limit=1000");
    expect(screen.getByRole("status", { name: "Loading..." })).toBeInTheDocument();
  });

  it("renders only exact Open entries and marks registered servers connected", () => {
    renderWithRouter(<ServerCatalog />);

    expect(screen.getByRole("region", { name: "Server catalog" })).toBeInTheDocument();
    const catalogList = screen.getByRole("list", { name: "Catalog servers" });
    expect(within(catalogList).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Globalping" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Public Notes" })).toBeInTheDocument();
    expect(screen.queryByText("Secret Service")).not.toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 servers shown");
    expect(screen.getByRole("button", { name: "View Globalping" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Public Notes" })).toBeInTheDocument();
    expect(screen.queryByText(/registration coming soon/i)).not.toBeInTheDocument();
  });

  it("opens a read-only server details dialog", async () => {
    const user = userEvent.setup();
    renderWithRouter(<ServerCatalog />);

    const viewButton = screen.getByRole("button", { name: "View Globalping" });
    await user.click(viewButton);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Globalping" })).toBeInTheDocument();
    expect(within(dialog).getByText("jsDelivr")).toBeInTheDocument();
    expect(within(dialog).getByText("STREAMABLEHTTP")).toBeInTheDocument();
    expect(within(dialog).getByText("observability")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(viewButton).toHaveFocus());
  });

  it("uses a labelled pressed-button group for catalog views", () => {
    renderWithRouter(<ServerCatalog />);

    const viewOptions = screen.getByRole("group", { name: "Catalog view" });
    expect(within(viewOptions).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(viewOptions).getByRole("button", { name: "Installed" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("restores search and installed state from the URL", () => {
    renderWithRouter(
      <ServerCatalog />,
      "/app/server-catalog?search=global&show_registered_only=true",
    );

    expect(screen.getByRole("button", { name: "Installed" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("searchbox", { name: "Search MCP servers" })).toHaveValue("global");
    expect(screen.getByRole("heading", { name: "Globalping" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Public Notes" })).not.toBeInTheDocument();
  });

  it("updates URL state for search and tabs", async () => {
    const user = userEvent.setup();
    renderWithRouter(<ServerCatalog />);

    await user.type(screen.getByRole("searchbox", { name: "Search MCP servers" }), "notes");
    expect(window.location.search).toContain("search=notes");
    expect(screen.getByRole("heading", { name: "Public Notes" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Globalping" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Installed" }));
    expect(window.location.search).toContain("show_registered_only=true");
    expect(
      screen.getByText("No MCP servers match the active search and filters."),
    ).toBeInTheDocument();
  });

  it("filters by category and reflects it in the URL", async () => {
    const user = userEvent.setup();
    renderWithRouter(<ServerCatalog />);

    await user.click(screen.getByRole("button", { name: /^Filters$/ }));
    expect(screen.getByRole("dialog", { name: "Filters" })).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "Category" }));
    await user.click(screen.getByRole("option", { name: "Productivity" }));

    await waitFor(() => expect(window.location.search).toContain("category=Productivity"));
    expect(screen.getByRole("heading", { name: "Public Notes" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Globalping" })).not.toBeInTheDocument();
  });

  it("supports repeatable OR tag filters", async () => {
    const user = userEvent.setup();
    renderWithRouter(<ServerCatalog />);

    await user.click(screen.getByRole("button", { name: /^Filters$/ }));
    await user.click(screen.getByRole("checkbox", { name: "network" }));
    await user.click(screen.getByRole("checkbox", { name: "documents" }));

    const params = new URLSearchParams(window.location.search);
    expect(params.getAll("tags")).toEqual(["network", "documents"]);
    expect(screen.getByRole("button", { name: "Filters, 2 active" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Globalping" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Public Notes" })).toBeInTheDocument();
  });

  it("shows explicit disabled and generic error states", () => {
    mockUseQuery.mockReturnValue(
      queryResult({ data: undefined, error: { message: "HTTP 404", status: 404 } }),
    );
    const { unmount } = renderWithRouter(<ServerCatalog />);

    expect(screen.getByText("Server catalog is disabled for this gateway.")).toBeInTheDocument();

    unmount();
    mockUseQuery.mockReturnValue(
      queryResult({ data: undefined, error: { message: "HTTP 500", status: 500 } }),
    );
    renderWithRouter(<ServerCatalog />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unable to load server catalog. Try again.",
    );
  });

  it("shows an empty state when the response has no Open entries", () => {
    mockUseQuery.mockReturnValue(
      queryResult({ data: { ...response, servers: [apiKeyServer], total: 1 } }),
    );

    renderWithRouter(<ServerCatalog />);

    expect(screen.getByText("No open MCP servers are available.")).toBeInTheDocument();
    expect(screen.queryByText("Secret Service")).not.toBeInTheDocument();
  });
});
