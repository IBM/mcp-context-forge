/**
 * Unit tests for plugins.js module
 * Tests: populatePluginFilters, filterPlugins, filterByHook, filterByTag,
 *        filterByAuthor, showPluginDetails, closePluginDetails
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  populatePluginFilters,
  filterPlugins,
  filterByHook,
  filterByTag,
  filterByAuthor,
  showPluginDetails,
  closePluginDetails,
} from "../../../mcpgateway/admin_ui/plugins.js";

// Mock dependencies
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

function createPluginCard(data) {
  const card = document.createElement("div");
  card.className = "plugin-card";
  card.dataset.name = data.name || "";
  card.dataset.description = data.description || "";
  card.dataset.author = data.author || "";
  card.dataset.mode = data.mode || "";
  card.dataset.status = data.status || "";
  card.dataset.hooks = data.hooks ? data.hooks.join(",") : "";
  card.dataset.tags = data.tags ? data.tags.join(",") : "";
  document.body.appendChild(card);
  return card;
}

function createFilterElements() {
  const elements = {
    search: document.createElement("input"),
    hookFilter: document.createElement("select"),
    tagFilter: document.createElement("select"),
    authorFilter: document.createElement("select"),
    modeFilter: document.createElement("select"),
    statusFilter: document.createElement("select"),
  };

  elements.search.id = "plugin-search";
  elements.hookFilter.id = "plugin-hook-filter";
  elements.tagFilter.id = "plugin-tag-filter";
  elements.authorFilter.id = "plugin-author-filter";
  elements.modeFilter.id = "plugin-mode-filter";
  elements.statusFilter.id = "plugin-status-filter";

  Object.values(elements).forEach((el) => document.body.appendChild(el));
  return elements;
}

// Helper to add option to select element (needed for JSDOM)
function addSelectOption(select, value) {
  const option = document.createElement("option");
  option.value = value;
  select.appendChild(option);
}

function createBadge(type, value) {
  const badge = document.createElement("span");
  badge.setAttribute("onclick", `Admin.filterBy${type.charAt(0).toUpperCase() + type.slice(1)}('${value}')`);
  badge.className = "bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600";
  badge.textContent = value;
  document.body.appendChild(badge);
  return badge;
}

// ---------------------------------------------------------------------------
// populatePluginFilters
// ---------------------------------------------------------------------------
describe("populatePluginFilters", () => {
  test("populates hook filter with unique hooks from plugin cards", () => {
    createPluginCard({ hooks: ["pre_request", "post_request"] });
    createPluginCard({ hooks: ["pre_request", "validate"] });

    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    document.body.appendChild(hookFilter);

    populatePluginFilters();

    const options = Array.from(hookFilter.querySelectorAll("option"));
    const values = options.map((o) => o.value);

    expect(values).toContain("pre_request");
    expect(values).toContain("post_request");
    expect(values).toContain("validate");
    expect(values.length).toBe(3);
  });

  test("formats hook names with proper capitalization", () => {
    createPluginCard({ hooks: ["pre_request"] });

    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    document.body.appendChild(hookFilter);

    populatePluginFilters();

    const option = hookFilter.querySelector("option");
    expect(option.value).toBe("pre_request");
    expect(option.textContent).toBe("Pre Request");
  });

  test("populates tag filter with unique tags", () => {
    createPluginCard({ tags: ["security", "logging"] });
    createPluginCard({ tags: ["security", "performance"] });

    const tagFilter = document.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    document.body.appendChild(tagFilter);

    populatePluginFilters();

    const options = Array.from(tagFilter.querySelectorAll("option"));
    const values = options.map((o) => o.value);

    expect(values).toContain("security");
    expect(values).toContain("logging");
    expect(values).toContain("performance");
    expect(values.length).toBe(3);
  });

  test("populates author filter with unique authors", () => {
    createPluginCard({ author: "alice" });
    createPluginCard({ author: "bob" });
    createPluginCard({ author: "alice" }); // duplicate

    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";
    document.body.appendChild(authorFilter);

    populatePluginFilters();

    const options = Array.from(authorFilter.querySelectorAll("option"));
    const values = options.map((o) => o.value);

    expect(values).toContain("alice");
    expect(values).toContain("bob");
    expect(values.length).toBe(2);
  });

  test("sorts authors alphabetically", () => {
    createPluginCard({ author: "zoe" });
    createPluginCard({ author: "alice" });
    createPluginCard({ author: "bob" });

    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";
    document.body.appendChild(authorFilter);

    populatePluginFilters();

    const options = Array.from(authorFilter.querySelectorAll("option"));
    const values = options.map((o) => o.value);

    expect(values[0]).toBe("alice");
    expect(values[1]).toBe("bob");
    expect(values[2]).toBe("zoe");
  });

  test("converts author to lowercase in value, capitalizes for display", () => {
    createPluginCard({ author: "Alice" });

    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";
    document.body.appendChild(authorFilter);

    populatePluginFilters();

    const option = authorFilter.querySelector("option");
    expect(option.value).toBe("alice");
    expect(option.textContent).toBe("Alice");
  });

  test("ignores empty hooks, tags, and authors", () => {
    createPluginCard({ hooks: ["", "valid_hook", "  "] });
    createPluginCard({ tags: ["", "valid_tag"] });
    createPluginCard({ author: "  " });

    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    const tagFilter = document.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";

    document.body.appendChild(hookFilter);
    document.body.appendChild(tagFilter);
    document.body.appendChild(authorFilter);

    populatePluginFilters();

    expect(hookFilter.querySelectorAll("option").length).toBe(1);
    expect(tagFilter.querySelectorAll("option").length).toBe(1);
    expect(authorFilter.querySelectorAll("option").length).toBe(0);
  });

  test("handles missing filter elements gracefully", () => {
    createPluginCard({ hooks: ["test"], tags: ["test"], author: "test" });
    expect(() => populatePluginFilters()).not.toThrow();
  });

  test("handles cards with no hooks, tags, or author", () => {
    createPluginCard({});

    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    const tagFilter = document.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";

    document.body.appendChild(hookFilter);
    document.body.appendChild(tagFilter);
    document.body.appendChild(authorFilter);

    expect(() => populatePluginFilters()).not.toThrow();
    expect(hookFilter.querySelectorAll("option").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// filterPlugins
// ---------------------------------------------------------------------------
describe("filterPlugins", () => {
  let consoleSpy;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  test("filters plugins by search query in name", () => {
    const card1 = createPluginCard({ name: "auth-plugin" });
    const card2 = createPluginCard({ name: "logger-plugin" });

    const filters = createFilterElements();
    filters.search.value = "auth";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters plugins by search query in description", () => {
    const card1 = createPluginCard({ description: "Handles authentication" });
    const card2 = createPluginCard({ description: "Logs requests" });

    const filters = createFilterElements();
    filters.search.value = "authentication";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters plugins by search query in author", () => {
    const card1 = createPluginCard({ author: "alice" });
    const card2 = createPluginCard({ author: "bob" });

    const filters = createFilterElements();
    filters.search.value = "alice";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("search is case-insensitive", () => {
    const card = createPluginCard({ name: "Auth-Plugin" });

    const filters = createFilterElements();
    filters.search.value = "AUTH";

    filterPlugins();

    expect(card.style.display).toBe("block");
  });

  test("filters by mode", () => {
    // Create all filter inputs
    const searchInput = document.createElement("input");
    searchInput.id = "plugin-search";
    searchInput.value = "";
    document.body.appendChild(searchInput);

    const modeFilter = document.createElement("select");
    modeFilter.id = "plugin-mode-filter";
    // Add options for JSDOM to work with select.value
    const option1 = document.createElement("option");
    option1.value = "enforce";
    modeFilter.appendChild(option1);
    const option2 = document.createElement("option");
    option2.value = "permissive";
    modeFilter.appendChild(option2);
    document.body.appendChild(modeFilter);

    const statusFilter = document.createElement("select");
    statusFilter.id = "plugin-status-filter";
    document.body.appendChild(statusFilter);

    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    document.body.appendChild(hookFilter);

    const tagFilter = document.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    document.body.appendChild(tagFilter);

    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";
    document.body.appendChild(authorFilter);

    // Create cards
    const card1 = createPluginCard({ mode: "enforce" });
    const card2 = createPluginCard({ mode: "permissive" });

    // Set filter value
    modeFilter.value = "enforce";

    // Filter
    filterPlugins();

    // Check results
    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters by status", () => {
    createFilterElements();
    const card1 = createPluginCard({ status: "active" });
    const card2 = createPluginCard({ status: "inactive" });

    const statusFilter = document.getElementById("plugin-status-filter");
    addSelectOption(statusFilter, "active");
    addSelectOption(statusFilter, "inactive");
    statusFilter.value = "active";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters by hook", () => {
    createFilterElements();
    const card1 = createPluginCard({ hooks: ["pre_request", "post_request"] });
    const card2 = createPluginCard({ hooks: ["validate"] });

    const hookFilter = document.getElementById("plugin-hook-filter");
    addSelectOption(hookFilter, "pre_request");
    addSelectOption(hookFilter, "validate");
    hookFilter.value = "pre_request";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters by tag", () => {
    createFilterElements();
    const card1 = createPluginCard({ tags: ["security", "auth"] });
    const card2 = createPluginCard({ tags: ["logging"] });

    const tagFilter = document.getElementById("plugin-tag-filter");
    addSelectOption(tagFilter, "security");
    addSelectOption(tagFilter, "logging");
    tagFilter.value = "security";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("filters by author", () => {
    createFilterElements();
    const card1 = createPluginCard({ author: "alice" });
    const card2 = createPluginCard({ author: "bob" });

    const authorFilter = document.getElementById("plugin-author-filter");
    addSelectOption(authorFilter, "alice");
    addSelectOption(authorFilter, "bob");
    authorFilter.value = "alice";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
  });

  test("author filter is case-insensitive and trims whitespace", () => {
    const card = createPluginCard({ author: " Alice " });

    const filters = createFilterElements();
    filters.authorFilter.value = "alice";

    filterPlugins();

    expect(card.style.display).toBe("block");
  });

  test("combines multiple filters with AND logic", () => {
    createFilterElements();
    const card1 = createPluginCard({
      name: "auth-plugin",
      mode: "enforce",
      hooks: ["pre_request"],
      author: "alice",
    });
    const card2 = createPluginCard({
      name: "auth-plugin",
      mode: "permissive",
      hooks: ["pre_request"],
      author: "alice",
    });
    const card3 = createPluginCard({
      name: "logger-plugin",
      mode: "enforce",
      hooks: ["post_request"],
      author: "bob",
    });

    const searchInput = document.getElementById("plugin-search");
    const modeFilter = document.getElementById("plugin-mode-filter");
    const hookFilter = document.getElementById("plugin-hook-filter");

    addSelectOption(modeFilter, "enforce");
    addSelectOption(modeFilter, "permissive");
    addSelectOption(hookFilter, "pre_request");
    addSelectOption(hookFilter, "post_request");

    searchInput.value = "auth";
    modeFilter.value = "enforce";
    hookFilter.value = "pre_request";

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("none");
    expect(card3.style.display).toBe("none");
  });

  test("shows all cards when no filters are set", () => {
    const card1 = createPluginCard({ name: "plugin1" });
    const card2 = createPluginCard({ name: "plugin2" });

    createFilterElements();

    filterPlugins();

    expect(card1.style.display).toBe("block");
    expect(card2.style.display).toBe("block");
  });

  test("handles missing filter elements gracefully", () => {
    createPluginCard({ name: "test" });
    expect(() => filterPlugins()).not.toThrow();
  });

  test("handles cards with missing data attributes", () => {
    const card = document.createElement("div");
    card.className = "plugin-card";
    document.body.appendChild(card);

    createFilterElements();

    expect(() => filterPlugins()).not.toThrow();
    expect(card.style.display).toBe("block");
  });
});

// ---------------------------------------------------------------------------
// filterByHook
// ---------------------------------------------------------------------------
describe("filterByHook", () => {
  let consoleSpy;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  test("sets hook filter value and triggers filtering", () => {
    createFilterElements();
    const card = createPluginCard({ hooks: ["pre_request"] });

    const hookFilter = document.getElementById("plugin-hook-filter");
    addSelectOption(hookFilter, "pre_request");
    hookFilter.scrollIntoView = vi.fn();

    filterByHook("pre_request");

    expect(hookFilter.value).toBe("pre_request");
    expect(card.style.display).toBe("block");
  });

  test("calls scrollIntoView on hook filter", () => {
    const hookFilter = document.createElement("select");
    hookFilter.id = "plugin-hook-filter";
    hookFilter.scrollIntoView = vi.fn();
    document.body.appendChild(hookFilter);

    createFilterElements();

    filterByHook("test_hook");

    expect(hookFilter.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "nearest",
    });
  });

  test("does nothing when hook filter is missing", () => {
    expect(() => filterByHook("test_hook")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterByTag
// ---------------------------------------------------------------------------
describe("filterByTag", () => {
  let consoleSpy;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  test("sets tag filter value and triggers filtering", () => {
    createFilterElements();
    const card = createPluginCard({ tags: ["security"] });

    const tagFilter = document.getElementById("plugin-tag-filter");
    addSelectOption(tagFilter, "security");
    tagFilter.scrollIntoView = vi.fn();

    filterByTag("security");

    expect(tagFilter.value).toBe("security");
    expect(card.style.display).toBe("block");
  });

  test("calls scrollIntoView on tag filter", () => {
    const tagFilter = document.createElement("select");
    tagFilter.id = "plugin-tag-filter";
    tagFilter.scrollIntoView = vi.fn();
    document.body.appendChild(tagFilter);

    createFilterElements();

    filterByTag("test_tag");

    expect(tagFilter.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "nearest",
    });
  });

  test("does nothing when tag filter is missing", () => {
    expect(() => filterByTag("test_tag")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// filterByAuthor
// ---------------------------------------------------------------------------
describe("filterByAuthor", () => {
  let consoleSpy;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  test("sets author filter value and triggers filtering", () => {
    createFilterElements();
    const card = createPluginCard({ author: "alice" });

    const authorFilter = document.getElementById("plugin-author-filter");
    addSelectOption(authorFilter, "alice");
    authorFilter.scrollIntoView = vi.fn();

    filterByAuthor("Alice");

    expect(authorFilter.value).toBe("alice");
    expect(card.style.display).toBe("block");
  });

  test("converts author to lowercase", () => {
    createFilterElements();

    const authorFilter = document.getElementById("plugin-author-filter");
    addSelectOption(authorFilter, "alice");
    authorFilter.scrollIntoView = vi.fn();

    filterByAuthor("ALICE");

    expect(authorFilter.value).toBe("alice");
  });

  test("calls scrollIntoView on author filter", () => {
    const authorFilter = document.createElement("select");
    authorFilter.id = "plugin-author-filter";
    authorFilter.scrollIntoView = vi.fn();
    document.body.appendChild(authorFilter);

    createFilterElements();

    filterByAuthor("test_author");

    expect(authorFilter.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "nearest",
    });
  });

  test("does nothing when author filter is missing", () => {
    expect(() => filterByAuthor("test_author")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// showPluginDetails
// ---------------------------------------------------------------------------
describe("showPluginDetails", () => {
  let fetchSpy;
  let consoleErrorSpy;

  beforeEach(() => {
    window.ROOT_PATH = "";
    fetchSpy = vi.spyOn(globalThis, "fetch");
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    consoleErrorSpy.mockRestore();
  });

  test("shows loading state initially", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    modal.classList.add("hidden");
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              ok: true,
              json: () => Promise.resolve({ name: "test" }),
            });
          }, 100);
        })
    );

    const promise = showPluginDetails("test-plugin");

    expect(modal.classList.contains("hidden")).toBe(false);
    expect(modalName.textContent).toBe("test-plugin");
    expect(modalContent.innerHTML).toContain("Loading...");

    await promise;
  });

  test("fetches plugin details with correct URL", async () => {
    window.ROOT_PATH = "/admin";

    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "test-plugin",
          description: "Test plugin",
          author: "Alice",
          version: "1.0.0",
          mode: "enforce",
          priority: 100,
          hooks: ["pre_request"],
          tags: ["security"],
          config: {},
        }),
    });

    await showPluginDetails("test-plugin");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/admin/plugins/test-plugin",
      expect.objectContaining({
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
        },
      })
    );
  });

  test("encodes plugin name in URL", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ name: "test plugin" }),
    });

    await showPluginDetails("test plugin");

    const [url] = fetchSpy.mock.calls[0];
    expect(url).toContain("test%20plugin");
  });

  test("renders plugin details on success", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "test-plugin",
          description: "A test plugin",
          author: "Alice",
          version: "1.2.3",
          mode: "enforce",
          priority: 100,
          hooks: ["pre_request", "post_request"],
          tags: ["security", "logging"],
          config: { setting1: "value1" },
        }),
    });

    await showPluginDetails("test-plugin");

    expect(modalContent.innerHTML).toContain("A test plugin");
    expect(modalContent.innerHTML).toContain("Alice");
    expect(modalContent.innerHTML).toContain("1.2.3");
    expect(modalContent.innerHTML).toContain("enforce");
    expect(modalContent.innerHTML).toContain("100");
    expect(modalContent.innerHTML).toContain("pre_request");
    expect(modalContent.innerHTML).toContain("post_request");
    expect(modalContent.innerHTML).toContain("security");
    expect(modalContent.innerHTML).toContain("logging");
    expect(modalContent.innerHTML).toContain("setting1");
  });

  test("handles missing optional fields", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          name: "minimal-plugin",
        }),
    });

    await showPluginDetails("minimal-plugin");

    expect(modalContent.innerHTML).toContain("No description available");
    expect(modalContent.innerHTML).toContain("Unknown");
    expect(modalContent.innerHTML).toContain("0.0.0");
  });

  test("applies correct styling for enforce mode", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ mode: "enforce" }),
    });

    await showPluginDetails("test");

    expect(modalContent.innerHTML).toContain("bg-red-100 text-red-800");
  });

  test("applies correct styling for permissive mode", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ mode: "permissive" }),
    });

    await showPluginDetails("test");

    expect(modalContent.innerHTML).toContain("bg-yellow-100 text-yellow-800");
  });

  test("shows error message on fetch failure", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: false,
      statusText: "Not Found",
    });

    await showPluginDetails("test-plugin");

    expect(modalContent.innerHTML).toContain("Error:");
    expect(modalContent.innerHTML).toContain("Failed to load plugin details: Not Found");
    expect(consoleErrorSpy).toHaveBeenCalled();
  });

  test("shows error message on network error", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockRejectedValue(new Error("Network error"));

    await showPluginDetails("test-plugin");

    expect(modalContent.innerHTML).toContain("Error:");
    expect(modalContent.innerHTML).toContain("Network error");
    expect(consoleErrorSpy).toHaveBeenCalled();
  });

  test("does nothing when modal elements are missing", async () => {
    consoleErrorSpy.mockRestore();
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    await showPluginDetails("test-plugin");

    expect(spy).toHaveBeenCalledWith("Plugin details modal elements not found");
    expect(fetchSpy).not.toHaveBeenCalled();

    spy.mockRestore();
  });

  test("does not show config section when config is empty", async () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    document.body.appendChild(modal);

    const modalName = document.createElement("div");
    modalName.id = "modal-plugin-name";
    document.body.appendChild(modalName);

    const modalContent = document.createElement("div");
    modalContent.id = "modal-plugin-content";
    document.body.appendChild(modalContent);

    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ config: {} }),
    });

    await showPluginDetails("test");

    expect(modalContent.innerHTML).not.toContain("Configuration");
  });
});

// ---------------------------------------------------------------------------
// closePluginDetails
// ---------------------------------------------------------------------------
describe("closePluginDetails", () => {
  test("hides the modal", () => {
    const modal = document.createElement("div");
    modal.id = "plugin-details-modal";
    modal.classList.remove("hidden");
    document.body.appendChild(modal);

    closePluginDetails();

    expect(modal.classList.contains("hidden")).toBe(true);
  });

  test("does nothing when modal is missing", () => {
    expect(() => closePluginDetails()).not.toThrow();
  });
});
