/**
 * Error parsing utilities for API responses
 */

interface ValidationError {
  msg?: string;
  loc?: string[];
}

interface ErrorBody {
  detail?: Array<ValidationError> | string;
  message?: string;
}

interface ApiError {
  body?: ErrorBody;
}

/**
 * Parses API error response into a user-friendly message
 * 
 * @param error - The error object from API call
 * @param fallbackMessage - Default message if parsing fails
 * @returns Formatted error message
 */
export function parseApiError(error: unknown, fallbackMessage: string): string {
  if (!error || typeof error !== "object") {
    return fallbackMessage;
  }

  const apiError = error as ApiError;

  // Check for simple message format first
  if (apiError.body?.message) {
    return apiError.body.message;
  }

  // Check for string detail
  if (typeof apiError.body?.detail === "string") {
    return apiError.body.detail;
  }

  // Check for validation errors format
  const details = apiError.body?.detail;
  if (Array.isArray(details) && details.length > 0) {
    // Extract error messages from validation errors
    const messages = details
      .map((err) => {
        const field = err.loc && err.loc.length > 1 ? err.loc[err.loc.length - 1] : "";
        const msg = err.msg || "Invalid value";
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
    return messages;
  }

  return fallbackMessage;
}
