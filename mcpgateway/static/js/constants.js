/* global marked, DOMPurify */

// Constants
export const MASKED_AUTH_VALUE = "*****";

/**
 * Header validation constants
 */
export const HEADER_NAME_REGEX = /^[A-Za-z0-9-]+$/;
export const MAX_HEADER_VALUE_LENGTH = 4096;

// Self-register on window.Admin for IIFE modules that depend on these
const Admin = window.Admin;
Admin.MASKED_AUTH_VALUE = MASKED_AUTH_VALUE;
Admin.HEADER_NAME_REGEX = HEADER_NAME_REGEX;
Admin.MAX_HEADER_VALUE_LENGTH = MAX_HEADER_VALUE_LENGTH;
