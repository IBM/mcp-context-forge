/* eslint-disable import-x/first */
/**
 * ====================================================================
 * ADMIN PUBLIC API - Facade for window.Admin namespace
 * ====================================================================
 *
 * This file imports all modules and exposes the public API to window.Admin
 * for use by HTMX and Alpine.js in templates.
 */

// Bootstrap MUST be first - initializes window.Admin before any modules run
import "./bootstrap.js";

// Get reference to the Admin namespace
const Admin = window.Admin;

// ===================================================================
// TIER 1: Foundation modules (fully converted to ES modules)
// ===================================================================
// Utils
import { copyToClipboard, handleKeydown, safeGetElement } from "./utils.js";

Admin.copyToClipboard = copyToClipboard;
Admin.handleKeydown = handleKeydown;
Admin.safeGetElement = safeGetElement;

// AppState
import { AppState } from "./appState.js";

Admin.AppState = AppState;

// ===================================================================
// TIER 2: Feature modules (fully converted to ES modules)
// ===================================================================

// Auth
import {
  toggleInputMask,
  addAuthHeader,
  removeAuthHeader,
  updateAuthHeadersJSON,
  fetchToolsForGateway,
} from "./auth.js";

Admin.toggleInputMask = toggleInputMask;
Admin.addAuthHeader = addAuthHeader;
Admin.removeAuthHeader = removeAuthHeader;
Admin.updateAuthHeadersJSON = updateAuthHeadersJSON;
Admin.fetchToolsForGateway = fetchToolsForGateway;

// Config Export
import {
  showConfigSelectionModal,
  generateAndShowConfig,
  copyConfigToClipboard,
  downloadConfig,
  goBackToSelection,
} from "./configExport.js";

Admin.showConfigSelectionModal = showConfigSelectionModal;
Admin.generateAndShowConfig = generateAndShowConfig;
Admin.copyConfigToClipboard = copyConfigToClipboard;
Admin.downloadConfig = downloadConfig;
Admin.goBackToSelection = goBackToSelection;

// File Transfer
import { previewImport, resetImportFile } from "./fileTransfer.js";

Admin.previewImport = previewImport;
Admin.resetImportFile = resetImportFile;

// Form Fields
import {
  searchTeamSelector,
  selectTeamFromSelector,
  updateRequestTypeOptions,
} from "./formFieldHandlers.js";

Admin.selectTeamFromSelector = selectTeamFromSelector;
Admin.searchTeamSelector = searchTeamSelector;
Admin.updateRequestTypeOptions = updateRequestTypeOptions;

// Form Handlers
import {
  handleToggleSubmit,
  handleSubmitWithConfirmation,
  handleDeleteSubmit,
} from "./formHandlers.js";

Admin.handleToggleSubmit = handleToggleSubmit;
Admin.handleSubmitWithConfirmation = handleSubmitWithConfirmation;
Admin.handleDeleteSubmit = handleDeleteSubmit;

// LLM Chat
import {
  connectLLMChat,
  disconnectLLMChat,
  handleChatInputKeydown,
  handleLLMModelChange,
  loadVirtualServersForChat,
  selectServerForChat,
  sendChatMessage,
} from "./llmChat.js";

Admin.connectLLMChat = connectLLMChat;
Admin.disconnectLLMChat = disconnectLLMChat;
Admin.handleChatInputKeydown = handleChatInputKeydown;
Admin.handleLLMModelChange = handleLLMModelChange;
Admin.loadVirtualServersForChat = loadVirtualServersForChat;
Admin.selectServerForChat = selectServerForChat;
Admin.sendChatMessage = sendChatMessage;

// LLM Models
import {
  checkLLMProviderHealth,
  closeLLMModelModal,
  closeLLMProviderModal,
  debouncedServerSideUserSearch,
  deleteLLMModel,
  deleteLLMProvider,
  editLLMModel,
  editLLMProvider,
  fetchLLMProviderModels,
  fetchModelsForModelModal,
  filterModelsByProvider,
  llmApiInfoApp,
  onLLMProviderTypeChange,
  onModelProviderChange,
  overviewDashboard,
  saveLLMModel,
  saveLLMProvider,
  serverSideUserSearch,
  showAddModelModal,
  showAddProviderModal,
  switchLLMSettingsTab,
  syncLLMProviderModels,
  toggleLLMModel,
  toggleLLMProvider,
} from "./llmModels.js";

Admin.checkLLMProviderHealth = checkLLMProviderHealth;
Admin.closeLLMModelModal = closeLLMModelModal;
Admin.closeLLMProviderModal = closeLLMProviderModal;
Admin.debouncedServerSideUserSearch = debouncedServerSideUserSearch;
Admin.deleteLLMModel = deleteLLMModel;
Admin.deleteLLMProvider = deleteLLMProvider;
Admin.editLLMModel = editLLMModel;
Admin.editLLMProvider = editLLMProvider;
Admin.fetchLLMProviderModels = fetchLLMProviderModels;
Admin.fetchModelsForModelModal = fetchModelsForModelModal;
Admin.filterModelsByProvider = filterModelsByProvider;
Admin.llmApiInfoApp = llmApiInfoApp;
Admin.onLLMProviderTypeChange = onLLMProviderTypeChange;
Admin.onModelProviderChange = onModelProviderChange;
Admin.overviewDashboard = overviewDashboard;
Admin.saveLLMModel = saveLLMModel;
Admin.saveLLMProvider = saveLLMProvider;
Admin.serverSideUserSearch = serverSideUserSearch;
Admin.showAddModelModal = showAddModelModal;
Admin.showAddProviderModal = showAddProviderModal;
Admin.switchLLMSettingsTab = switchLLMSettingsTab;
Admin.syncLLMProviderModels = syncLLMProviderModels;
Admin.toggleLLMModel = toggleLLMModel;
Admin.toggleLLMProvider = toggleLLMProvider;

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
  viewRoot,
  editRoot,
  exportRoot,
} from "./mcpController.js";

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
Admin.viewRoot = viewRoot;
Admin.editRoot = editRoot;
Admin.exportRoot = exportRoot;

// Metrics
import { retryLoadMetrics, switchTopPerformersTab } from "./metrics.js";

Admin.retryLoadMetrics = retryLoadMetrics;
Admin.switchTopPerformersTab = switchTopPerformersTab;

// Modals
import { closeModal } from "./modals.js";

Admin.closeModal = closeModal;

// Resources
import { initResourceSelect } from "./resources.js";

Admin.initResourceSelect = initResourceSelect;

// Prompts
import { initPromptSelect, testPrompt, runPromptTest } from "./prompts.js";

Admin.initPromptSelect = initPromptSelect;
Admin.testPrompt = testPrompt;
Admin.runPromptTest = runPromptTest;

// Tabs
import { showTab } from "./tabs.js";

Admin.showTab = showTab;

// Tags
import { clearTagFilter } from "./tags.js";

Admin.clearTagFilter = clearTagFilter;

// Tokens
import { getAuthToken, getTeamNameById } from "./tokens.js";

Admin.getAuthToken = getAuthToken;
Admin.getTeamNameById = getTeamNameById;

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
} from "./tools.js";

Admin.initToolSelect = initToolSelect;
Admin.testTool = testTool;
Admin.enrichTool = enrichTool;
Admin.generateToolTestCases = generateToolTestCases;
Admin.generateTestCases = generateTestCases;
Admin.validateTool = validateTool;
Admin.runToolTest = runToolTest;
Admin.viewTool = viewTool;

// ===================================================================
// TIER 3 & 4: Domain and Orchestration modules (still using IIFE)
// These modules will attach their functions directly to window.Admin
// ===================================================================

// Import IIFE modules - they self-register on window.Admin
import "./app.js";
import "./events.js";

console.log("🚀 ContextForge MCP Gateway Admin API initialized");
