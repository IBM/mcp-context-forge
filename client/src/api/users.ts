/**
 * Users API service
 *
 * Wraps /admin/users backend endpoint for user management.
 */

import { api } from "./client";
import type { User, CreateUserRequest, UsersResponse } from "../types/user";
import { sanitizeString, sanitizePassword } from "@/lib/sanitize";

/**
 * Validates email format
 * @param email - The email to validate
 * @returns The validated email
 * @throws Error if email is invalid
 */
function validateEmail(email: string): string {
  if (!email || typeof email !== "string") {
    throw new Error("Invalid email");
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    throw new Error("Invalid email format");
  }

  return email;
}

/**
 * Sanitizes and validates user creation request
 * @param data - The user creation data
 * @returns Sanitized request data
 */
function sanitizeCreateUserRequest(data: CreateUserRequest): CreateUserRequest {
  return {
    email: validateEmail(sanitizeString(data.email, 255)),
    password: sanitizePassword(data.password, 1000), // pragma: allowlist secret
    full_name: data.full_name ? sanitizeString(data.full_name, 255) : undefined,
    is_admin: data.is_admin ?? false,
    is_active: data.is_active ?? true,
    password_change_required: data.password_change_required ?? false,
  };
}

export const usersApi = {
  /**
   * List all users with cursor-based pagination
   */
  list: (params?: {
    cursor?: string;
    limit?: number;
    signal?: AbortSignal;
  }): Promise<UsersResponse> => {
    const searchParams = new URLSearchParams();

    // Add cursor if provided
    if (params?.cursor) {
      searchParams.set("cursor", params.cursor);
    }

    // Validate and clamp limit (1-100)
    if (params?.limit !== undefined) {
      const limit = Number.isFinite(params.limit)
        ? Math.max(1, Math.min(100, Math.floor(params.limit)))
        : 25;
      searchParams.set("limit", limit.toString());
    }

    const query = searchParams.toString();
    return api.get(`/admin/users${query ? `?${query}` : ""}`, undefined, params?.signal);
  },

  /**
   * Create a new user
   */
  create: (data: CreateUserRequest): Promise<User> => {
    const sanitizedData = sanitizeCreateUserRequest(data);
    return api.post("/admin/users", sanitizedData);
  },

  /**
   * Get a single user by email
   */
  get: (email: string): Promise<User> => {
    const validEmail = validateEmail(email);
    return api.get(`/admin/users/${encodeURIComponent(validEmail)}`);
  },

  /**
   * Delete a user
   */
  delete: (email: string): Promise<void> => {
    const validEmail = validateEmail(email);
    return api.delete(`/admin/users/${encodeURIComponent(validEmail)}`);
  },
};
