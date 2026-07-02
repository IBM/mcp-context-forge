import { describe, it, expect, vi, beforeEach } from "vitest";
import { createTeam, addTeamMember, deleteTeam } from "./teams";
import { api } from "./client";

vi.mock("@/api/client", () => ({
  api: {
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("createTeam", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs to /teams with the payload and returns the created team", async () => {
    const team = { id: "team-1", name: "Engineering" };
    vi.mocked(api.post).mockResolvedValue(team);

    const payload = {
      name: "Engineering",
      description: "Eng team",
      visibility: "private" as const,
      max_members: 100,
    };
    const result = await createTeam(payload);

    expect(api.post).toHaveBeenCalledWith("/teams", payload);
    expect(result).toEqual(team);
  });

  it("propagates errors from the API", async () => {
    const error = new Error("boom");
    vi.mocked(api.post).mockRejectedValue(error);

    await expect(createTeam({ name: "X", visibility: "public" })).rejects.toThrow("boom");
  });
});

describe("addTeamMember", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs the member to the team's members endpoint", async () => {
    vi.mocked(api.post).mockResolvedValue(undefined);

    await addTeamMember("team-1", { email: "user@example.com", role: "member" });

    expect(api.post).toHaveBeenCalledWith("/teams/team-1/members", {
      email: "user@example.com",
      role: "member",
    });
  });

  it("URL-encodes the team id", async () => {
    vi.mocked(api.post).mockResolvedValue(undefined);

    await addTeamMember("team/with space", { email: "a@b.com", role: "owner" });

    expect(api.post).toHaveBeenCalledWith("/teams/team%2Fwith%20space/members", {
      email: "a@b.com",
      role: "owner",
    });
  });

  it("propagates errors from the API", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("already a member"));

    await expect(
      addTeamMember("team-1", { email: "user@example.com", role: "member" }),
    ).rejects.toThrow("already a member");
  });
});

describe("deleteTeam", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("DELETEs the URL-encoded team id", async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);

    await deleteTeam("team/1");

    expect(api.delete).toHaveBeenCalledWith("/teams/team%2F1");
  });
});
