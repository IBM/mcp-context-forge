import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "@/i18n";
import { searchAdminEntities } from "@/api/search";
import { useAuthContext } from "@/auth/AuthContext";
import { useRouter } from "@/router";
import { HeaderQuickNav } from "./HeaderQuickNav";

vi.mock("@/api/search", () => ({
  searchAdminEntities: vi.fn(),
}));

vi.mock("@/auth/AuthContext", () => ({
  useAuthContext: vi.fn(),
}));

vi.mock("@/router", () => ({
  useRouter: vi.fn(),
}));

const originalPlatform = window.navigator.platform;
const mockNavigate = vi.fn();

function renderQuickNav() {
  return render(
    <I18nProvider>
      <HeaderQuickNav />
    </I18nProvider>,
  );
}

const defaultAuthContext = {
  user: {
    email: "viewer@example.com",
    full_name: "Viewer",
    is_admin: false,
    is_active: true,
    auth_provider: "email",
    email_verified: true,
    password_change_required: false,
  },
  isAuthenticated: true,
  isLoading: false,
  selectedTeamId: null,
  login: vi.fn(),
  logout: vi.fn(),
  setSelectedTeamId: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({
    path: "/app/",
    params: {},
    navigate: mockNavigate,
  });
  vi.mocked(useAuthContext).mockReturnValue(defaultAuthContext);
  vi.mocked(searchAdminEntities).mockResolvedValue({
    query: "server",
    entity_types: ["gateways"],
    limit_per_type: 8,
    results: {},
    groups: [],
    items: [],
    count: 0,
  });
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: originalPlatform,
  });
});

describe("HeaderQuickNav", () => {
  it("renders a search input", () => {
    renderQuickNav();

    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
  });

  it("starts collapsed and expands on focus", async () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    expect(input).toHaveAttribute("data-expanded", "false");
    expect(screen.getByText("Ctrl K")).toBeInTheDocument();

    fireEvent.focus(input);

    expect(input).toHaveAttribute("data-expanded", "true");
  });

  it("keeps the typed value in the input", () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.change(input, { target: { value: "servers" } });

    expect(input).toHaveValue("servers");
  });

  it("keeps focus in the input when the popover opens on the first character", async () => {
    const user = userEvent.setup();

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    await user.click(input);
    await user.keyboard("s");

    expect(input).toHaveFocus();
    expect(screen.getByText("Type at least 2 characters to search.")).toBeInTheDocument();
  });

  it("focuses the search input when the icon button is clicked", async () => {
    const user = userEvent.setup();

    renderQuickNav();

    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(screen.getByRole("searchbox", { name: "Search" })).toHaveFocus();
    });
  });

  it("shows the macOS shortcut symbol on Apple platforms", async () => {
    Object.defineProperty(window.navigator, "platform", {
      configurable: true,
      value: "MacIntel",
    });

    renderQuickNav();

    expect(await screen.findByText("⌘ K")).toBeInTheDocument();
  });

  it("focuses the search input when the shortcut is pressed", () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    return waitFor(() => {
      expect(input).toHaveFocus();
      expect(input).toHaveAttribute("data-expanded", "true");
    });
  });

  it("stays expanded after blur when the query has content", () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.change(input, { target: { value: "servers" } });
    fireEvent.blur(input);

    expect(input).toHaveAttribute("data-expanded", "true");
  });

  it("collapses again on blur when the query is empty", async () => {
    const user = userEvent.setup();

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    await user.click(input);
    fireEvent.blur(input);

    expect(input).toHaveAttribute("data-expanded", "false");
  });

  it("prevents the form from submitting", () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    const form = input.closest("form");
    expect(form).not.toBeNull();

    const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
    form!.dispatchEvent(submitEvent);

    expect(submitEvent.defaultPrevented).toBe(true);
  });

  it("does not search before the minimum query length", () => {
    vi.useFakeTimers();
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "s" } });
    vi.advanceTimersByTime(300);

    expect(searchAdminEntities).not.toHaveBeenCalled();
    expect(screen.getByText("Type at least 2 characters to search.")).toBeInTheDocument();
  });

  it("searches /admin/search and renders grouped results", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "server",
      entity_types: ["gateways"],
      limit_per_type: 8,
      results: {},
      groups: [
        {
          entity_type: "gateways",
          count: 1,
          items: [
            {
              id: "gateway-1",
              name: "Payments MCP",
              description: "Handles payment tools",
            },
          ],
        },
      ],
      items: [],
      count: 1,
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "server" } });

    await waitFor(() => {
      expect(searchAdminEntities).toHaveBeenCalledWith(
        expect.objectContaining({
          query: "server",
          entityTypes: ["servers", "gateways", "tools", "resources", "prompts", "agents", "teams"],
          limitPerType: 8,
          teamId: null,
        }),
      );
    });

    expect(await screen.findByText("MCP Servers")).toBeInTheDocument();
    expect(screen.getByText("Payments MCP")).toBeInTheDocument();
    expect(screen.getByText("Handles payment tools")).toBeInTheDocument();
  });

  it("shows an error state when global search fails", async () => {
    vi.mocked(searchAdminEntities).mockRejectedValue(new Error("Search failed"));

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "server" } });

    expect(await screen.findByText("Search failed. Please try again.")).toBeInTheDocument();
  });

  it("includes users for platform admins and selected team scope", async () => {
    vi.mocked(useAuthContext).mockReturnValue({
      ...defaultAuthContext,
      selectedTeamId: "team-123",
      user: { ...defaultAuthContext.user, is_admin: true },
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "alice" } });

    await waitFor(() => {
      expect(searchAdminEntities).toHaveBeenCalledWith(
        expect.objectContaining({
          query: "alice",
          entityTypes: expect.arrayContaining(["users"]),
          teamId: "team-123",
        }),
      );
    });
  });

  it("navigates to the owning page when a result is selected", async () => {
    const user = userEvent.setup();
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "tool",
      entity_types: ["tools"],
      limit_per_type: 8,
      results: {},
      groups: [
        {
          entity_type: "tools",
          count: 1,
          items: [{ id: "tool-1", name: "Weather Tool" }],
        },
      ],
      items: [],
      count: 1,
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "tool" } });
    await user.click(await screen.findByText("Weather Tool"));

    expect(mockNavigate).toHaveBeenCalledWith("/app/tools?selected=tool-1&search=tool");
  });

  it("navigates to the first result when the form is submitted", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "resource",
      entity_types: ["resources"],
      limit_per_type: 8,
      results: {},
      groups: [
        {
          entity_type: "resources",
          count: 1,
          items: [{ id: "resource-1", name: "Catalog Resource" }],
        },
      ],
      items: [],
      count: 1,
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    const form = input.closest("form");
    expect(form).not.toBeNull();

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "resource" } });
    await screen.findByText("Catalog Resource");
    fireEvent.submit(form!);

    expect(mockNavigate).toHaveBeenCalledWith("/app/resources?selected=resource-1&search=resource");
  });

  it("navigates to the focused result with keyboard navigation", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "tool",
      entity_types: ["tools"],
      limit_per_type: 8,
      results: {},
      groups: [
        {
          entity_type: "tools",
          count: 2,
          items: [
            { id: "tool-1", name: "Weather Tool" },
            { id: "tool-2", name: "Calendar Tool" },
          ],
        },
      ],
      items: [],
      count: 2,
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "tool" } });
    await screen.findByText("Calendar Tool");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });

    const calendarOption = screen.getByRole("option", { name: /Calendar Tool/ });
    expect(input).toHaveAttribute("aria-activedescendant", calendarOption.id);
    expect(calendarOption).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "Enter" });

    expect(mockNavigate).toHaveBeenCalledWith("/app/tools?selected=tool-2&search=tool");
  });

  it("keeps keyboard focus inside result boundaries", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "tool",
      entity_types: ["tools"],
      limit_per_type: 8,
      results: {},
      groups: [
        {
          entity_type: "tools",
          count: 2,
          items: [
            { id: "tool-1", name: "Weather Tool" },
            { id: "tool-2", name: "Calendar Tool" },
          ],
        },
      ],
      items: [],
      count: 2,
    });

    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "tool" } });
    await screen.findByText("Calendar Tool");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(screen.getByRole("option", { name: /Weather Tool/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: /Calendar Tool/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows an empty state when no results match", async () => {
    renderQuickNav();

    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "missing" } });

    expect(await screen.findByText("No matching results.")).toBeInTheDocument();
  });

  type SearchResult = Awaited<ReturnType<typeof searchAdminEntities>>;

  it("resolves result labels from fallback fields across multiple groups", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "q",
      entity_types: [],
      limit_per_type: 8,
      results: {},
      items: [],
      count: 4,
      groups: [
        {
          entity_type: "resources",
          count: 2,
          items: [
            { id: "r1", uri: "resource://only-uri" },
            { id: "r2", full_name: "Full Name Person" },
          ],
        },
        {
          entity_type: "tools",
          count: 1,
          items: [{ id: "t1", slug: "tool-slug" }],
        },
      ],
    } as unknown as SearchResult);

    renderQuickNav();
    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "query" } });

    expect(await screen.findByText("resource://only-uri")).toBeInTheDocument();
    expect(screen.getByText("Full Name Person")).toBeInTheDocument();
    expect(screen.getByText("tool-slug")).toBeInTheDocument();
  });

  it("shows a searching state while the request is in flight", async () => {
    vi.mocked(searchAdminEntities).mockReturnValue(new Promise<SearchResult>(() => {}));

    renderQuickNav();
    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "query" } });

    expect(await screen.findByText("Searching...")).toBeInTheDocument();
  });

  it("ignores abort errors without showing an error state", async () => {
    vi.mocked(searchAdminEntities).mockRejectedValue(new DOMException("aborted", "AbortError"));

    renderQuickNav();
    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "query" } });

    // The abort is swallowed, so no error message is rendered.
    await waitFor(() => expect(searchAdminEntities).toHaveBeenCalled());
    expect(screen.queryByText(/failed|error/i)).not.toBeInTheDocument();
  });

  it("closes the results popover on Escape", async () => {
    vi.mocked(searchAdminEntities).mockResolvedValue({
      query: "q",
      entity_types: [],
      limit_per_type: 8,
      results: {},
      items: [],
      count: 1,
      groups: [{ entity_type: "gateways", count: 1, items: [{ id: "g1", name: "Payments MCP" }] }],
    } as unknown as SearchResult);

    renderQuickNav();
    const input = screen.getByRole("searchbox", { name: "Search" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "query" } });

    expect(await screen.findByText("Payments MCP")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByText("Payments MCP")).not.toBeInTheDocument();
    });
  });
});
