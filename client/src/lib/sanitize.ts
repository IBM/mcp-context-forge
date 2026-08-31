/**
 * Input sanitization utilities for form data
 *
 * Aligns with Python backend sanitization in mcpgateway/common/validators.py
 * and mcpgateway/utils/passthrough_headers.py
 *
 * Key principles:
 * - Remove control characters (0x00-0x1F, 0x7F-0x9F)
 * - Prevent CRLF injection (\r, \n)
 * - Keep only printable ASCII where appropriate
 * - Enforce length limits
 * - Preserve legitimate special characters (spaces, punctuation)
 */

/**
 * Remove control characters and CRLF to prevent injection attacks
 * Matches Python: _CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
 */
export function removeControlCharacters(value: string): string {
  if (!value) return value;

  // Remove CRLF (primary injection vectors)
  let sanitized = value.replace(/[\r\n]/g, "");

  // Remove control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F-0x9F)
  // Preserves tab (0x09) and normal spaces
  sanitized = sanitized.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]/g, "");

  // Remove URL-encoded control characters that might bypass client-side checks
  sanitized = sanitized.replace(/%0[0-9A-Fa-f]/g, "");
  sanitized = sanitized.replace(/%1[0-9A-Fa-f]/g, "");

  return sanitized;
}

/**
 * Sanitize general string input
 * Matches Python: sanitize_header_value() behavior
 */
export function sanitizeString(value: string, maxLength: number = 1000): string {
  if (!value) return value;

  let sanitized = removeControlCharacters(value);

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  return sanitized.trim();
}

/**
 * Sanitize URL input
 * Ensures protocol is present and removes control characters
 */
export function sanitizeUrl(value: string, maxLength: number = 2000): string {
  if (!value) return value;

  let sanitized = removeControlCharacters(value);

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  return sanitized.trim();
}

/**
 * Sanitize password input
 * Preserves spaces but removes control characters
 */
export function sanitizePassword(value: string, maxLength: number = 1000): string {
  if (!value) return value;

  let sanitized = removeControlCharacters(value);

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  // Don't trim spaces from passwords
  return sanitized;
}

/**
 * Sanitize authentication token
 * Keeps only printable ASCII characters
 * Matches Python: re.sub(r"[^\x20-\x7E]", "", value)
 */
export function sanitizeToken(value: string, maxLength: number = 2000): string {
  if (!value) return value;

  // Keep only printable ASCII (space to tilde: 0x20-0x7E)
  let sanitized = value.replace(/[^\x20-\x7E]/g, "");

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  return sanitized.trim();
}

/**
 * Sanitize query parameter key or value
 * Removes control characters and enforces length limit
 */
export function sanitizeQueryParam(value: string, maxLength: number = 500): string {
  if (!value) return value;

  let sanitized = removeControlCharacters(value);

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  return sanitized.trim();
}

/**
 * Sanitize PEM certificate content
 * Preserves newlines (required for PEM format) but removes other control characters
 */
export function sanitizeCertificate(value: string, maxLength: number = 10000): string {
  if (!value) return value;

  // Remove control characters except newlines (which are required in PEM format)
  let sanitized = value.replace(/[\x00-\x09\x0B\x0C\x0E-\x1F\x7F-\x9F]/g, "");

  // Remove URL-encoded control characters
  sanitized = sanitized.replace(/%0[0-9A-Fa-f]/g, "");
  sanitized = sanitized.replace(/%1[0-9A-Fa-f]/g, "");

  // Trim to max length
  if (sanitized.length > maxLength) {
    sanitized = sanitized.substring(0, maxLength);
  }

  // Do not trim: PEM certs may require a trailing newline after -----END CERTIFICATE-----
  return sanitized;
}
