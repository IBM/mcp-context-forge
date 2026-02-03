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
// Utils
import {
  safeGetElement,
} from './utils.js';

Admin.safeGetElement = safeGetElement;

// AppState
import { AppState } from './appState.js';

Admin.AppState = AppState;

// ===================================================================
// TIER 2: Feature modules (fully converted to ES modules)
// ===================================================================

// Modals
import {
  closeModal,
} from './modals.js';

Admin.closeModal = closeModal;

// Auth
import {
  toggleInputMask,
  addAuthHeader,
  removeAuthHeader,
  updateAuthHeadersJSON,
  fetchToolsForGateway,
} from './auth.js';

Admin.toggleInputMask = toggleInputMask;
Admin.addAuthHeader = addAuthHeader;
Admin.removeAuthHeader = removeAuthHeader;
Admin.updateAuthHeadersJSON = updateAuthHeadersJSON;
Admin.fetchToolsForGateway = fetchToolsForGateway;

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
  testResource,
  runResourceTest,
  viewResource,
  editResource,
  viewPrompt,
  editPrompt,
  viewGateway,
  editGateway,
  viewServer,
  editServer,
} from './mcpController.js';

Admin.editTool = editTool;
Admin.viewAgent = viewAgent;
Admin.editA2AAgent = editA2AAgent;
Admin.testResource = testResource;
Admin.runResourceTest = runResourceTest;
Admin.viewResource = viewResource;
Admin.editResource = editResource;
Admin.viewPrompt = viewPrompt;
Admin.editPrompt = editPrompt;
Admin.viewGateway = viewGateway;
Admin.editGateway = editGateway;
Admin.viewServer = viewServer;
Admin.editServer = editServer;

// Tools
import {
  initToolSelect,
  testTool,
  enrichTool,
  generateToolTestCases,
  generateTestCases,
  validateTool,
  runToolTest,
  viewTool,
} from './tools.js';

Admin.initToolSelect = initToolSelect;
Admin.testTool = testTool;
Admin.enrichTool = enrichTool;
Admin.generateToolTestCases = generateToolTestCases;
Admin.generateTestCases = generateTestCases;
Admin.validateTool = validateTool;
Admin.runToolTest = runToolTest;
Admin.viewTool = viewTool;

// Resources
import {
  initResourceSelect,
} from './resources.js';

Admin.initResourceSelect = initResourceSelect;

// Prompts
import { 
  initPromptSelect,
  testPrompt,
  runPromptTest,
 } from './prompts.js';
 
Admin.initPromptSelect = initPromptSelect;
Admin.testPrompt = testPrompt;
Admin.runPromptTest = runPromptTest;

// Config Export
import {
  showConfigSelectionModal,
  generateAndShowConfig,
  copyConfigToClipboard,
  downloadConfig,
  goBackToSelection,
} from './configExport.js';

Admin.showConfigSelectionModal = showConfigSelectionModal;
Admin.generateAndShowConfig = generateAndShowConfig;
Admin.copyConfigToClipboard = copyConfigToClipboard;
Admin.downloadConfig = downloadConfig;
Admin.goBackToSelection = goBackToSelection;

// Tabs
import {
  showTab,
} from './tabs.js';

Admin.showTab = showTab;

// Tags
import {
  clearTagFilter,
} from './tags.js';

Admin.clearTagFilter = clearTagFilter

// Metrics
import {
  retryLoadMetrics,
  switchTopPerformersTab,
} from './metrics.js';


Admin.retryLoadMetrics = retryLoadMetrics;
Admin.switchTopPerformersTab = switchTopPerformersTab;

// ===================================================================
// TIER 3 & 4: Domain and Orchestration modules (still using IIFE)
// These modules will attach their functions directly to window.Admin
// ===================================================================

// Import IIFE modules - they self-register on window.Admin
import './events.js';
import './app.js';

console.log("🚀 ContextForge MCP Gateway Admin API initialized");
