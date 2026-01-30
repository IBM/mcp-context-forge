/**
 * ====================================================================
 * ADMIN PUBLIC API - Facade for window.Admin namespace
 * ====================================================================
 *
 * This file imports all modules and exposes the public API to window.Admin
 * for use by HTMX and Alpine.js in templates.
 */

// Bootstrap MUST be first - initializes window.Admin before any modules run
import './bootstrap.js';

// Get reference to the Admin namespace
const Admin = window.Admin;

// ===================================================================
// TIER 1: Foundation modules (fully converted to ES modules)
// ===================================================================

// Constants
import {
    MASKED_AUTH_VALUE,
    HEADER_NAME_REGEX,
    MAX_HEADER_VALUE_LENGTH,
} from './constants.js';

Admin.MASKED_AUTH_VALUE = MASKED_AUTH_VALUE;
Admin.HEADER_NAME_REGEX = HEADER_NAME_REGEX;
Admin.MAX_HEADER_VALUE_LENGTH = MAX_HEADER_VALUE_LENGTH;

// Utils
import {
    createMemoizedInit,
    safeGetElement,
    isInactiveChecked,
    fetchWithTimeout,
    handleFetchError,
    showErrorMessage,
    showSuccessMessage,
    parseUriTemplate,
} from './utils.js';

Admin.createMemoizedInit = createMemoizedInit;
Admin.safeGetElement = safeGetElement;
Admin.isInactiveChecked = isInactiveChecked;
Admin.fetchWithTimeout = fetchWithTimeout;
Admin.handleFetchError = handleFetchError;
Admin.showErrorMessage = showErrorMessage;
Admin.showSuccessMessage = showSuccessMessage;
Admin.parseUriTemplate = parseUriTemplate;

// AppState
import {
    AppState,
    registerCleanupToolTestState,
} from './appState.js';

Admin.AppState = AppState;
Admin.registerCleanupToolTestState = registerCleanupToolTestState;

// ===================================================================
// TIER 2: Feature modules (fully converted to ES modules)
// ===================================================================

// Security
import {
    escapeHtml,
    extractApiError,
    parseErrorResponse,
    validatePassthroughHeader,
    validateInputName,
    validateUrl,
    validateJson,
    safeSetInnerHTML,
} from './security.js';

Admin.escapeHtml = escapeHtml;
Admin.extractApiError = extractApiError;
Admin.parseErrorResponse = parseErrorResponse;
Admin.validatePassthroughHeader = validatePassthroughHeader;
Admin.validateInputName = validateInputName;
Admin.validateUrl = validateUrl;
Admin.validateJson = validateJson;
Admin.safeSetInnerHTML = safeSetInnerHTML;

// Modals
import {
    openModal,
    closeModal,
    resetModalState,
    registerModalCleanup,
} from './modals.js';

Admin.openModal = openModal;
Admin.closeModal = closeModal;
Admin.resetModalState = resetModalState;
Admin.registerModalCleanup = registerModalCleanup;

// Auth
import {
    toggleInputMask,
    addAuthHeader,
    removeAuthHeader,
    updateAuthHeadersJSON,
    loadAuthHeaders,
    fetchToolsForGateway,
    handleAuthTypeSelection,
} from './auth.js';

Admin.toggleInputMask = toggleInputMask;
Admin.addAuthHeader = addAuthHeader;
Admin.removeAuthHeader = removeAuthHeader;
Admin.updateAuthHeadersJSON = updateAuthHeadersJSON;
Admin.loadAuthHeaders = loadAuthHeaders;
Admin.fetchToolsForGateway = fetchToolsForGateway;
Admin.handleAuthTypeSelection = handleAuthTypeSelection;

// ===================================================================
// TIER 3 & 4: Domain and Orchestration modules (still using IIFE)
// These modules will attach their functions directly to window.Admin
// ===================================================================

// Import IIFE modules - they self-register on window.Admin
import './metrics.js';
import './mcpController.js';
import './tabs.js';
import './events.js';
import './app.js';

console.log("🚀 ContextForge MCP Gateway Admin API initialized");
