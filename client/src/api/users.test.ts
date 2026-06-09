import { describe, it, expect, vi, beforeEach } from "vitest";
import { usersApi, deleteUser } from "./users";
import { api } from "./client";
import { ApiError } from "./client";

vi.mock("./client", () => ({
  api: {
    delete: vi.fn(),
    get: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public body: unknown,
      message: string,
    ) {
      super(message);
    }
  },
}));

describe("usersApi.delete", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should delete user successfully", async () => {
    const mockResponse = { success: true, message: "User deleted" };
    vi.mocked(api.delete).mockResolvedValue(mockResponse);

    const result = await usersApi.delete("test@example.com");

    expect(api.delete).toHaveBeenCalledWith("/auth/email/admin/users/test%40example.com");
    expect(result).toEqual(mockResponse);
  });

  it("should handle self-deletion error", async () => {
    vi.mocked(api.delete).mockRejectedValue(
      new ApiError(400, { detail: "Cannot delete your own account" }, "HTTP 400"),
    );

    await expect(usersApi.delete("self@example.com")).rejects.toThrow(ApiError);
  });

  it("should handle last admin error", async () => {
    vi.mocked(api.delete).mockRejectedValue(
      new ApiError(
        400,
        { detail: "Cannot delete the last remaining admin user" },
        "HTTP 400",
      ),
    );

    await expect(usersApi.delete("admin@example.com")).rejects.toThrow(ApiError);
  });

  it("should handle not found error", async () => {
    vi.mocked(api.delete).mockRejectedValue(
      new ApiError(404, { detail: "User not found" }, "HTTP 404"),
    );

    await expect(usersApi.delete("notfound@example.com")).rejects.toThrow(ApiError);
  });

  it("should handle permission error", async () => {
    vi.mocked(api.delete).mockRejectedValue(
      new ApiError(403, { detail: "Insufficient permissions" }, "HTTP 403"),
    );

    await expect(usersApi.delete("user@example.com")).rejects.toThrow(ApiError);
  });

  it("should validate email format", async () => {
    expect(() => usersApi.delete("")).toThrow("Invalid user email");
    expect(() => usersApi.delete("invalid")).toThrow("Invalid email format");
    expect(() => usersApi.delete("@example.com")).toThrow("Invalid email format");
    expect(() => usersApi.delete("user@")).toThrow("Invalid email format");
  });

  it("should encode email in URL", async () => {
    const mockResponse = { success: true, message: "User deleted" };
    vi.mocked(api.delete).mockResolvedValue(mockResponse);

    await usersApi.delete("user+test@example.com");

    expect(api.delete).toHaveBeenCalledWith("/auth/email/admin/users/user%2Btest%40example.com");
  });
});

describe("deleteUser (backward compatibility)", () => {
  it("should be an alias for usersApi.delete", () => {
    expect(deleteUser).toBe(usersApi.delete);
  });
});

describe("usersApi.list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should fetch users with default parameters", async () => {
    const mockResponse = { users: [], nextCursor: undefined };
    vi.mocked(api.get).mockResolvedValue(mockResponse);

    const result = await usersApi.list();

    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?include_pagination=true",
      undefined,
      undefined,
    );
    expect(result).toEqual(mockResponse);
  });

  it("should fetch users with cursor", async () => {
    const mockResponse = { users: [], nextCursor: "next-cursor" };
    vi.mocked(api.get).mockResolvedValue(mockResponse);

    await usersApi.list({ cursor: "test-cursor" });

    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?cursor=test-cursor&include_pagination=true",
      undefined,
      undefined,
    );
  });

  it("should fetch users with limit", async () => {
    const mockResponse = { users: [], nextCursor: undefined };
    vi.mocked(api.get).mockResolvedValue(mockResponse);

    await usersApi.list({ limit: 50 });

    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=50&include_pagination=true",
      undefined,
      undefined,
    );
  });

  it("should clamp limit to valid range", async () => {
    const mockResponse = { users: [], nextCursor: undefined };
    vi.mocked(api.get).mockResolvedValue(mockResponse);

    await usersApi.list({ limit: 200 });
    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=100&include_pagination=true",
      undefined,
      undefined,
    );

    vi.clearAllMocks();
    await usersApi.list({ limit: 0 });
    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?limit=1&include_pagination=true",
      undefined,
      undefined,
    );
  });

  it("should pass abort signal", async () => {
    const mockResponse = { users: [], nextCursor: undefined };
    vi.mocked(api.get).mockResolvedValue(mockResponse);
    const signal = new AbortController().signal;

    await usersApi.list({ signal });

    expect(api.get).toHaveBeenCalledWith(
      "/auth/email/admin/users?include_pagination=true",
      undefined,
      signal,
    );
  });
});
