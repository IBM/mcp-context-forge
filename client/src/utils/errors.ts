/**
 * Wrapper for async operations with standardized error handling
 *
 * @param operation - The async operation to execute
 * @param errorMessage - Context message for logging
 * @returns The operation result or null on error
 */
export async function withErrorHandling<T>(
  operation: () => Promise<T>,
  errorMessage: string,
): Promise<T | null> {
  try {
    return await operation();
  } catch (err) {
    const sanitized = sanitizeError(err);
    console.error(errorMessage, sanitized);
    return null;
  }
}

/**
 * Extracts error message from FastAPI validation error format
 *
 * @param body - The error body from API response
 * @returns Extracted error message or null if not found
 */
export function extractApiErrorDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") {
    return null;
  }

  const errorBody = body as { detail?: string | Array<{ msg: string }> };

  if (!errorBody.detail) {
    return null;
  }

  // String detail
  if (typeof errorBody.detail === "string") {
    return errorBody.detail;
  }

  // Array of validation errors
  if (Array.isArray(errorBody.detail) && errorBody.detail.length > 0) {
    return errorBody.detail[0].msg || null;
  }

  return null;
}

/**
 * Sanitizes error messages to prevent information leakage
 *
 * @param err - The error object to sanitize
 * @returns A safe, user-friendly error message
 */
export function sanitizeError(err: unknown): string {
  // Log full error for debugging in development
  if (import.meta.env.DEV) {
    console.error("[DEV] Full error:", err);
  }

  if (err instanceof Error) {
    const message = err.message.toLowerCase();

    // Network errors
    if (message.includes("network") || message.includes("timeout") || message.includes("fetch")) {
      return "Network error. Please check your connection and try again.";
    }

    // Authentication errors
    if (message.includes("401") || message.includes("unauthorized")) {
      return "Authentication required. Please log in again.";
    }

    // Permission errors
    if (message.includes("403") || message.includes("forbidden")) {
      return "You don't have permission to perform this action.";
    }

    // Not found errors
    if (message.includes("404") || message.includes("not found")) {
      return "The requested resource was not found.";
    }

    // Server errors
    if (message.includes("500") || message.includes("502") || message.includes("503")) {
      return "Server error. Please try again later.";
    }

    // Log unmatched errors for monitoring
    console.warn("[Security] Unmatched error type:", err.constructor.name);

    // Generic fallback - don't expose raw error messages
    return "An error occurred. Please try again.";
  }

  return "An unexpected error occurred.";
}
