import {
  createTeam,
  addTeamMember,
  updateTeamMember,
  removeTeamMember,
  listTeamMembers,
  deleteTeam,
  updateTeam,
} from "./teams";
import { api } from "./client";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
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

describe("updateTeam", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("PUTs to the URL-encoded team id with the payload and returns the team", async () => {
    const team = { id: "team-1", name: "Engineering" };
    vi.mocked(api.put).mockResolvedValue(team);

    const payload = {
      name: "Engineering",
      description: "Eng team",
      visibility: "public" as const,
      max_members: 50,
    };
    const result = await updateTeam("team/1", payload);

    expect(api.put).toHaveBeenCalledWith("/teams/team%2F1", payload);
    expect(result).toEqual(team);
  });

  it("propagates errors from the API", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("boom"));

    await expect(updateTeam("team-1", { name: "X" })).rejects.toThrow("boom");
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

describe("listTeamMembers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("GETs the team's members endpoint and returns the array", async () => {
    const members = [
      { user_email: "a@example.com", role: "owner", joined_at: "2024-01-01T00:00:00Z" },
    ];
    vi.mocked(api.get).mockResolvedValue(members);

    const result = await listTeamMembers("team-1");

    expect(api.get).toHaveBeenCalledWith("/teams/team-1/members");
    expect(result).toEqual(members);
  });

  it("URL-encodes the team id", async () => {
    vi.mocked(api.get).mockResolvedValue([]);

    await listTeamMembers("team/1");

    expect(api.get).toHaveBeenCalledWith("/teams/team%2F1/members");
  });

  it("propagates errors from the API", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("forbidden"));

    await expect(listTeamMembers("team-1")).rejects.toThrow("forbidden");
  });
});

describe("updateTeamMember", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("PUTs the role to the member endpoint", async () => {
    vi.mocked(api.put).mockResolvedValue(undefined);

    await updateTeamMember("team-1", "user@example.com", { role: "owner" });

    expect(api.put).toHaveBeenCalledWith("/teams/team-1/members/user%40example.com", {
      role: "owner",
    });
  });

  it("URL-encodes both the team id and the user email", async () => {
    vi.mocked(api.put).mockResolvedValue(undefined);

    await updateTeamMember("team/1", "a b@example.com", { role: "member" });

    expect(api.put).toHaveBeenCalledWith("/teams/team%2F1/members/a%20b%40example.com", {
      role: "member",
    });
  });

  it("propagates errors from the API", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("not found"));

    await expect(updateTeamMember("team-1", "user@example.com", { role: "owner" })).rejects.toThrow(
      "not found",
    );
  });
});

describe("removeTeamMember", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("DELETEs the member endpoint", async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);

    await removeTeamMember("team-1", "user@example.com");

    expect(api.delete).toHaveBeenCalledWith("/teams/team-1/members/user%40example.com");
  });

  it("URL-encodes both the team id and the user email", async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);

    await removeTeamMember("team/1", "a b@example.com");

    expect(api.delete).toHaveBeenCalledWith("/teams/team%2F1/members/a%20b%40example.com");
  });

  it("propagates errors from the API", async () => {
    vi.mocked(api.delete).mockRejectedValue(new Error("cannot remove last owner"));

    await expect(removeTeamMember("team-1", "user@example.com")).rejects.toThrow(
      "cannot remove last owner",
    );
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
