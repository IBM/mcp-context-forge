/**
 * Application-wide constants
 */

/**
 * Form validation constants
 */
export const VALIDATION = {
  /** Maximum length for email fields */
  MAX_EMAIL_LENGTH: 255,

  /** Maximum length for password fields */
  MAX_PASSWORD_LENGTH: 1000,

  /** Minimum password length requirement */
  MIN_PASSWORD_LENGTH: 8,

  /** Maximum length for name fields */
  MAX_NAME_LENGTH: 255,
} as const;

/**
 * API pagination constants
 */
export const PAGINATION = {
  /** Default page size for list requests */
  DEFAULT_LIMIT: 25,

  /** Minimum page size */
  MIN_LIMIT: 1,

  /** Maximum page size */
  MAX_LIMIT: 100,
} as const;
