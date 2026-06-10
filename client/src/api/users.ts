/**
 * Users API service
 *
 * Wraps /auth/email/admin/users backend endpoints for user management.
 */

import { api } from "./client";

export interface DeleteUserResponse {
  success: boolean;
  message: string;
}

/**
 * Validates user email to prevent injection attacks
 * @param email - The user email to validate
 * @returns The validated email
 * @throws Error if email is invalid
 */
function validateUserEmail(email: string): string {
  if (!email || typeof email !== "string") {
    throw new Error("Invalid user email");
  }

  const normalized = email.trim().toLowerCase();

  // RFC 5321: max 254 chars
  if (normalized.length > 254) {
    throw new Error("Email too long");
  }

  // Stricter RFC 5322 subset: rejects quoted local-parts, bare IPs, etc.
  const emailRegex =
    /^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i;

  if (!emailRegex.test(normalized)) {
    throw new Error("Invalid email format");
  }

  return normalized;
}

export const usersApi = {
  /**
   * Delete a user by email.
   *
   * @throws {ApiError} 400 - Cannot delete self or last admin
   * @throws {ApiError} 403 - Insufficient permissions
   * @throws {ApiError} 404 - User not found
   */
  delete: (email: string): Promise<DeleteUserResponse> => {
    const validEmail = validateUserEmail(email);
    return api.delete<DeleteUserResponse>(
      `/auth/email/admin/users/${encodeURIComponent(validEmail)}`,
    );
  },
};

export const deleteUser = usersApi.delete;
