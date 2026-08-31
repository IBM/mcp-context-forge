import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { searchEntities } from "./search";

vi.mock("./client", () => ({
  api: {
    get: vi.fn(),
  },
}));

describe("searchEntities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("builds the /v1/search URL with entity types and per-type limit", async () => {
    const response = {
      query: "tool",
      entity_types: ["tools"],
      limit_per_type: 8,
      results: { tools: [] },
      groups: [],
      items: [],
      count: 0,
    };
    vi.mocked(api.get).mockResolvedValue(response);

    await searchEntities({
      query: " tool ",
      entityTypes: ["tools", "resources"],
      limitPerType: 6,
    });

    expect(api.get).toHaveBeenCalledWith(
      "/v1/search?q=tool&limit_per_type=6&entity_types=tools%2Cresources",
      undefined,
      undefined,
    );
  });

  it("adds team scope and forwards the abort signal when provided", async () => {
    const controller = new AbortController();
    vi.mocked(api.get).mockResolvedValue({
      query: "alpha",
      entity_types: ["teams"],
      limit_per_type: 8,
      results: { teams: [] },
      groups: [],
      items: [],
      count: 0,
    });

    await searchEntities({
      query: "alpha",
      entityTypes: ["teams"],
      teamId: "team-123",
      signal: controller.signal,
    });

    expect(api.get).toHaveBeenCalledWith(
      "/v1/search?q=alpha&limit_per_type=8&entity_types=teams&team_id=team-123",
      undefined,
      controller.signal,
    );
  });
});
