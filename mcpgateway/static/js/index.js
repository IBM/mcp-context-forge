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
  isAdminUser,
  copyJsonToClipboard,
} from './utils.js';

Admin.createMemoizedInit = createMemoizedInit;
Admin.safeGetElement = safeGetElement;
Admin.isInactiveChecked = isInactiveChecked;
Admin.fetchWithTimeout = fetchWithTimeout;
Admin.handleFetchError = handleFetchError;
Admin.showErrorMessage = showErrorMessage;
Admin.showSuccessMessage = showSuccessMessage;
Admin.parseUriTemplate = parseUriTemplate;
Admin.isAdminUser = isAdminUser;
Admin.copyJsonToClipboard = copyJsonToClipboard;

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

// Form Handlers
import {
  handleToggleSubmit,
  handleSubmitWithConfirmation,
  handleDeleteSubmit,
} from './formHandlers.js';

Admin.handleToggleSubmit = handleToggleSubmit;
Admin.handleSubmitWithConfirmation = handleSubmitWithConfirmation;
Admin.handleDeleteSubmit = handleDeleteSubmit;

// MCP Controller
import {
  editTool,
  viewAgent,
  editA2AAgent,
  safeSetValue,
  toggleA2AAuthFields,
  testResource,
  openResourceTestModal,
  runResourceTest,
  viewResource,
  editResource,
  viewPrompt,
  editPrompt,
  viewGateway,
  editGateway,
  viewServer,
  editServer,
  setEditServerAssociations,
} from './mcpController.js';

Admin.editTool = editTool;
Admin.viewAgent = viewAgent;
Admin.editA2AAgent = editA2AAgent;
Admin.safeSetValue = safeSetValue;
Admin.toggleA2AAuthFields = toggleA2AAuthFields;
Admin.testResource = testResource;
Admin.openResourceTestModal = openResourceTestModal;
Admin.runResourceTest = runResourceTest;
Admin.viewResource = viewResource;
Admin.editResource = editResource;
Admin.viewPrompt = viewPrompt;
Admin.editPrompt = editPrompt;
Admin.viewGateway = viewGateway;
Admin.editGateway = editGateway;
Admin.viewServer = viewServer;
Admin.editServer = editServer;
Admin.setEditServerAssociations = setEditServerAssociations;

// Tabs
import {
  isAdminOnlyTab,
  getDefaultTabName,
  getTableNamesForTab,
  cleanUpUrlParamsForTab,
  showTab,
} from './tabs.js';

Admin.isAdminOnlyTab = isAdminOnlyTab;
Admin.getDefaultTabName = getDefaultTabName;
Admin.getTableNamesForTab = getTableNamesForTab;
Admin.cleanUpUrlParamsForTab = cleanUpUrlParamsForTab;
Admin.showTab = showTab;

// Tools
import {
  initToolSelect,
  testTool,
  loadTools,
  enrichTool,
  generateToolTestCases,
  generateTestCases,
  validateTool,
  runToolValidation,
  runToolAgentValidation,
  runToolTest,
  cleanupToolTestState,
  cleanupToolTestModal,
  viewTool,
} from './tools.js';

Admin.initToolSelect = initToolSelect;
Admin.testTool = testTool;
Admin.loadTools = loadTools;
Admin.enrichTool = enrichTool;
Admin.generateToolTestCases = generateToolTestCases;
Admin.generateTestCases = generateTestCases;
Admin.validateTool = validateTool;
Admin.runToolValidation = runToolValidation;
Admin.runToolAgentValidation = runToolAgentValidation;
Admin.runToolTest = runToolTest;
Admin.cleanupToolTestState = cleanupToolTestState;
Admin.cleanupToolTestModal = cleanupToolTestModal;
Admin.viewTool = viewTool;

// Resources
import {
  initResourceSelect,
  cleanupResourceTestModal,
} from './resources.js';

Admin.initResourceSelect = initResourceSelect;
Admin.cleanupResourceTestModal = cleanupResourceTestModal;

// Prompts
import { 
  initPromptSelect,
  testPrompt,
  buildPromptTestForm,
  runPromptTest,
  cleanupPromptTestModal,
 } from './prompts.js';
 
Admin.initPromptSelect = initPromptSelect;
Admin.testPrompt = testPrompt;
Admin.buildPromptTestForm = buildPromptTestForm;
Admin.runPromptTest = runPromptTest;
Admin.cleanupPromptTestModal = cleanupPromptTestModal;
 
// Servers
import { loadServers } from './servers.js'

Admin.loadServers = loadServers;

// Config Export
import {
  showConfigSelectionModal,
  getCatalogUrl,
  generateAndShowConfig,
  exportServerConfig,
  generateConfig,
  showConfigDisplayModal,
  copyConfigToClipboard,
  downloadConfig,
  goBackToSelection,
} from './configExport.js';

Admin.showConfigSelectionModal = showConfigSelectionModal;
Admin.getCatalogUrl = getCatalogUrl;
Admin.generateAndShowConfig = generateAndShowConfig;
Admin.exportServerConfig = exportServerConfig;
Admin.generateConfig = generateConfig;
Admin.showConfigDisplayModal = showConfigDisplayModal;
Admin.copyConfigToClipboard = copyConfigToClipboard;
Admin.downloadConfig = downloadConfig;
Admin.goBackToSelection = goBackToSelection;

// Tags
import {
  extractAvailableTags,
  updateAvailableTags,
  filterEntitiesByTags,
  addTagToFilter,
  updateFilterEmptyState,
  clearTagFilter,
  initializeTagFiltering,
} from './tags.js';

Admin.extractAvailableTags = extractAvailableTags
Admin.updateAvailableTags = updateAvailableTags
Admin.filterEntitiesByTags = filterEntitiesByTags
Admin.addTagToFilter = addTagToFilter
Admin.updateFilterEmptyState = updateFilterEmptyState
Admin.clearTagFilter = clearTagFilter
Admin.initializeTagFiltering = initializeTagFiltering

// Metrics
import {
  loadAggregatedMetrics,
  loadMetricsInternal,
  showMetricsLoading,
  hideMetricsLoading,
  showMetricsError,
  retryLoadMetrics,
  showMetricsPlaceholder,
  displayMetrics,
  switchTopPerformersTab,
  createSystemSummaryCard,
  createKPISection,
  formatValue,
  extractKPIData,
  updateKPICards,
  calculateSuccessRate,
  formatNumber,
  formatLastUsed,
  showTopPerformerTab,
  createStandardPaginationControls,
  updateTableRows,
  createPerformanceCard,
  createRecentActivitySection,
  createMetricsCard,
} from './metrics.js';

Admin.loadAggregatedMetrics = loadAggregatedMetrics;
Admin.loadMetricsInternal = loadMetricsInternal;
Admin.showMetricsLoading = showMetricsLoading;
Admin.hideMetricsLoading = hideMetricsLoading;
Admin.showMetricsError = showMetricsError;
Admin.retryLoadMetrics = retryLoadMetrics;
Admin.showMetricsPlaceholder = showMetricsPlaceholder;
Admin.displayMetrics = displayMetrics;
Admin.switchTopPerformersTab = switchTopPerformersTab;
Admin.createSystemSummaryCard = createSystemSummaryCard;
Admin.createKPISection = createKPISection;
Admin.formatValue = formatValue;
Admin.extractKPIData = extractKPIData;
Admin.updateKPICards = updateKPICards;
Admin.calculateSuccessRate = calculateSuccessRate;
Admin.formatNumber = formatNumber;
Admin.formatLastUsed = formatLastUsed;
Admin.showTopPerformerTab = showTopPerformerTab;
Admin.createStandardPaginationControls = createStandardPaginationControls;
Admin.updateTableRows = updateTableRows;
Admin.createPerformanceCard = createPerformanceCard;
Admin.createRecentActivitySection = createRecentActivitySection;
Admin.createMetricsCard = createMetricsCard;

// ===================================================================
// TIER 3 & 4: Domain and Orchestration modules (still using IIFE)
// These modules will attach their functions directly to window.Admin
// ===================================================================

// Import IIFE modules - they self-register on window.Admin
import './events.js';
import './app.js';

console.log("🚀 ContextForge MCP Gateway Admin API initialized");
