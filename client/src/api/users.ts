/**
 * Users API service
 *
 * Wraps /admin/users backend endpoint for user management.
 */

import { api } from "./client";
import type { User, CreateUserRequest, UsersResponse } from "../types/user";
import { sanitizeString, sanitizePassword } from "@/lib/sanitize";
import { VALIDATION, PAGINATION } from "@/lib/constants";

/**
 * Validates email format with strict RFC 5322 compliance
 * @param email - The email to validate
 * @returns The validated email
 * @throws Error if email is invalid
 */
function validateEmail(email: string): string {
  if (!email || typeof email !== "string") {
    throw new Error("Invalid email");
  }

  // Strict email validation: alphanumeric + allowed special chars, no scripts
  const emailRegex = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;
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
    email: validateEmail(sanitizeString(data.email, VALIDATION.MAX_EMAIL_LENGTH)),
    password: sanitizePassword(data.password, VALIDATION.MAX_PASSWORD_LENGTH), // pragma: allowlist secret
    full_name: data.full_name ? sanitizeString(data.full_name, VALIDATION.MAX_NAME_LENGTH) : undefined,
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

    // Validate and clamp limit
    if (params?.limit !== undefined) {
      const limit = Number.isFinite(params.limit)
        ? Math.max(PAGINATION.MIN_LIMIT, Math.min(PAGINATION.MAX_LIMIT, Math.floor(params.limit)))
        : PAGINATION.DEFAULT_LIMIT;
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
