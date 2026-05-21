import { describe, it, expect, vi, beforeEach } from "vitest";
import { usersApi } from "./users";
import { api } from "./client";
import type { CreateUserRequest, User, UsersResponse } from "../types/user";

vi.mock("./client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("usersApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("list", () => {
    it("should fetch users without params", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: undefined,
      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);

      const result = await usersApi.list();

      expect(api.get).toHaveBeenCalledWith("/admin/users", undefined, undefined);
      expect(result).toEqual(mockResponse);
    });

    it("should fetch users with cursor", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: "next123",

      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);

      await usersApi.list({ cursor: "cursor123" });

      expect(api.get).toHaveBeenCalledWith("/admin/users?cursor=cursor123", undefined, undefined);
    });

    it("should fetch users with limit", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: undefined,
      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);

      await usersApi.list({ limit: 50 });

      expect(api.get).toHaveBeenCalledWith("/admin/users?limit=50", undefined, undefined);
    });

    it("should clamp limit to max 100", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: undefined,
      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);

      await usersApi.list({ limit: 200 });

      expect(api.get).toHaveBeenCalledWith("/admin/users?limit=100", undefined, undefined);
    });

    it("should clamp limit to min 1", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: undefined,
      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);

      await usersApi.list({ limit: -5 });

      expect(api.get).toHaveBeenCalledWith("/admin/users?limit=1", undefined, undefined);
    });

    it("should pass abort signal", async () => {
      const mockResponse: UsersResponse = {
        users: [],
        nextCursor: undefined,
      };
      vi.mocked(api.get).mockResolvedValue(mockResponse);
      const controller = new AbortController();

      await usersApi.list({ signal: controller.signal });

      expect(api.get).toHaveBeenCalledWith("/admin/users", undefined, controller.signal);
    });
  });

  describe("create", () => {
    it("should create user with valid data", async () => {
      const mockUser: User = {
        email: "test@example.com",
        full_name: "Test User",
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: false,
        failed_login_attempts: 0,
        is_locked: false,
        password_change_required: false,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      };
      vi.mocked(api.post).mockResolvedValue(mockUser);

      const data: CreateUserRequest = {
        email: "test@example.com",
        password: "SecurePass123!",
        full_name: "Test User",
        is_admin: false,
        is_active: true,
        password_change_required: false,
      };

      const result = await usersApi.create(data);

      expect(api.post).toHaveBeenCalledWith(
        "/admin/users",
        expect.objectContaining({
          email: "test@example.com",
          full_name: "Test User",
          is_admin: false,
          is_active: true,
          password_change_required: false,
        }),
      );
      expect(result).toEqual(mockUser);
    });

    it("should sanitize email with whitespace", async () => {
      const mockUser: User = {
        email: "test@example.com",
        full_name: undefined,
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: false,
        failed_login_attempts: 0,
        is_locked: false,
        password_change_required: false,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      };
      vi.mocked(api.post).mockResolvedValue(mockUser);

      const data: CreateUserRequest = {
        email: "  test@example.com  ",
        password: "SecurePass123!",
      };

      await usersApi.create(data);

      expect(api.post).toHaveBeenCalledWith(
        "/admin/users",
        expect.objectContaining({
          email: "test@example.com",
        }),
      );
    });

    it("should reject invalid email format", async () => {
      const data: CreateUserRequest = {
        email: "invalid-email",
        password: "SecurePass123!",
      };

      await expect(usersApi.create(data)).rejects.toThrow("Invalid email format");
      expect(api.post).not.toHaveBeenCalled();
    });

    it("should reject empty email", async () => {
      const data: CreateUserRequest = {
        email: "",
        password: "SecurePass123!",
      };

      await expect(usersApi.create(data)).rejects.toThrow("Invalid email");
      expect(api.post).not.toHaveBeenCalled();
    });

    it("should reject email without @", async () => {
      const data: CreateUserRequest = {
        email: "testexample.com",
        password: "SecurePass123!",
      };

      await expect(usersApi.create(data)).rejects.toThrow("Invalid email format");
      expect(api.post).not.toHaveBeenCalled();
    });

    it("should reject email without domain", async () => {
      const data: CreateUserRequest = {
        email: "test@",
        password: "SecurePass123!",
      };

      await expect(usersApi.create(data)).rejects.toThrow("Invalid email format");
      expect(api.post).not.toHaveBeenCalled();
    });

    it("should apply default values for optional fields", async () => {
      const mockUser: User = {
        email: "test@example.com",
        full_name: undefined,
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: false,
        failed_login_attempts: 0,
        is_locked: false,
        password_change_required: false,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      };
      vi.mocked(api.post).mockResolvedValue(mockUser);

      const data: CreateUserRequest = {
        email: "test@example.com",
        password: "SecurePass123!",
      };

      await usersApi.create(data);

      expect(api.post).toHaveBeenCalledWith(
        "/admin/users",
        expect.objectContaining({
          is_admin: false,
          is_active: true,
          password_change_required: false,
        }),
      );
    });
  });

  describe("get", () => {
    it("should fetch user by email", async () => {
      const mockUser: User = {
        email: "test@example.com",
        full_name: "Test User",
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: false,
        failed_login_attempts: 0,
        is_locked: false,
        password_change_required: false,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      };
      vi.mocked(api.get).mockResolvedValue(mockUser);

      const result = await usersApi.get("test@example.com");

      expect(api.get).toHaveBeenCalledWith("/admin/users/test%40example.com");
      expect(result).toEqual(mockUser);
    });

    it("should URL encode email with special characters", async () => {
      const mockUser: User = {
        email: "test+tag@example.com",
        full_name: "Test User",
        is_admin: false,
        is_active: true,
        auth_provider: "local",
        email_verified: false,
        failed_login_attempts: 0,
        is_locked: false,
        password_change_required: false,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      };
      vi.mocked(api.get).mockResolvedValue(mockUser);

      await usersApi.get("test+tag@example.com");

      expect(api.get).toHaveBeenCalledWith("/admin/users/test%2Btag%40example.com");
    });

    it("should reject invalid email", async () => {
      await expect(usersApi.get("invalid-email")).rejects.toThrow("Invalid email format");
      expect(api.get).not.toHaveBeenCalled();
    });
  });

  describe("delete", () => {
    it("should delete user by email", async () => {
      vi.mocked(api.delete).mockResolvedValue(undefined);

      await usersApi.delete("test@example.com");

      expect(api.delete).toHaveBeenCalledWith("/admin/users/test%40example.com");
    });

    it("should URL encode email with special characters", async () => {
      vi.mocked(api.delete).mockResolvedValue(undefined);

      await usersApi.delete("test+tag@example.com");

      expect(api.delete).toHaveBeenCalledWith("/admin/users/test%2Btag%40example.com");
    });

    it("should reject invalid email", async () => {
      await expect(usersApi.delete("invalid-email")).rejects.toThrow("Invalid email format");
      expect(api.delete).not.toHaveBeenCalled();
    });
  });
});
