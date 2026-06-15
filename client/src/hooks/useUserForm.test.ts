import { describe, it, expect, beforeEach, vi } from "vitest";
import { createOptimisticUser } from "./useUserForm";
import type { CreateUserRequest } from "@/types/user";

describe("useUserForm", () => {
  describe("createOptimisticUser", () => {
    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2024-01-15T10:30:00.000Z"));
    });

    it("should create optimistic user with all provided fields", () => {
      const userData: CreateUserRequest = {
        email: "test@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Test User",
        is_admin: true,
        is_active: false,
        password_change_required: true,
      };

      const result = createOptimisticUser(userData);

      expect(result).toEqual({
        email: "test@example.com",
        full_name: "Test User",
        is_admin: true,
        is_active: false,
        auth_provider: "email",
        created_at: "2024-01-15T10:30:00.000Z",
        email_verified: false,
        password_change_required: true,
        failed_login_attempts: 0,
        is_locked: false,
      });
    });

    it("should use default values for optional fields", () => {
      const userData: CreateUserRequest = {
        email: "minimal@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Minimal User",
      };

      const result = createOptimisticUser(userData);

      expect(result).toEqual({
        email: "minimal@example.com",
        full_name: "Minimal User",
        is_admin: false,
        is_active: true,
        auth_provider: "email",
        created_at: "2024-01-15T10:30:00.000Z",
        email_verified: false,
        password_change_required: false,
        failed_login_attempts: 0,
        is_locked: false,
      });
    });

    it("should handle explicit false values correctly", () => {
      const userData: CreateUserRequest = {
        email: "explicit@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Explicit User",
        is_admin: false,
        is_active: false,
        password_change_required: false,
      };

      const result = createOptimisticUser(userData);

      expect(result.is_admin).toBe(false);
      expect(result.is_active).toBe(false);
      expect(result.password_change_required).toBe(false);
    });

    it("should always set auth_provider to email", () => {
      const userData: CreateUserRequest = {
        email: "provider@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Provider User",
      };

      const result = createOptimisticUser(userData);

      expect(result.auth_provider).toBe("email");
    });

    it("should always set email_verified to false", () => {
      const userData: CreateUserRequest = {
        email: "verified@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Verified User",
      };

      const result = createOptimisticUser(userData);

      expect(result.email_verified).toBe(false);
    });

    it("should always set failed_login_attempts to 0", () => {
      const userData: CreateUserRequest = {
        email: "attempts@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Attempts User",
      };

      const result = createOptimisticUser(userData);

      expect(result.failed_login_attempts).toBe(0);
    });

    it("should always set is_locked to false", () => {
      const userData: CreateUserRequest = {
        email: "locked@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Locked User",
      };

      const result = createOptimisticUser(userData);

      expect(result.is_locked).toBe(false);
    });

    it("should use current timestamp for created_at", () => {
      const userData: CreateUserRequest = {
        email: "timestamp@example.com",
        password: "password123", // pragma: allowlist secret
        full_name: "Timestamp User",
      };

      const result = createOptimisticUser(userData);

      expect(result.created_at).toBe("2024-01-15T10:30:00.000Z");
    });
  });
});
