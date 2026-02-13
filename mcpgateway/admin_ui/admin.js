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
import {
  copyToClipboard,
  handleKeydown,
  refreshLogs,
  safeGetElement,
  showErrorMessage,
  showNotification,
  showSuccessMessage,
} from "./utils.js";

Admin.copyToClipboard = copyToClipboard;
Admin.handleKeydown = handleKeydown;
Admin.refreshLogs = refreshLogs;
Admin.safeGetElement = safeGetElement;
Admin.showErrorMessage = showErrorMessage;
Admin.showNotification = showNotification;
Admin.showSuccessMessage = showSuccessMessage;

// AppState
import { AppState } from "./appState.js";

Admin.AppState = AppState;

// Security
import { safeReplaceState, logRestrictedContext } from "./security.js";

Admin.safeReplaceState = safeReplaceState;
Admin.logRestrictedContext = logRestrictedContext;

// ===================================================================
// TIER 2: Feature modules (fully converted to ES modules)
// ===================================================================

import {
  editA2AAgent,
  viewA2AAgent,
} from "./a2aAgents.js"

Admin.editA2AAgent = editA2AAgent;
Admin.viewA2AAgent = viewA2AAgent;

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

// CA Certificates
import {
  validateCACertFiles,
  formatFileSize,
  updateBodyLabel,
} from "./caCertificate.js";

Admin.validateCACertFiles = validateCACertFiles;
Admin.formatFileSize = formatFileSize;
Admin.updateBodyLabel = updateBodyLabel;

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

// Filtering
import { clearSearch, filterServerTable } from "./filters.js";

Admin.clearSearch = clearSearch;
Admin.filterServerTable = filterServerTable;

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

// Gateways
import { 
  editGateway,
  testGateway,
  viewGateway,
} from "./gateway.js";

Admin.editGateway = editGateway;
Admin.testGateway = testGateway;
Admin.viewGateway = viewGateway;

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

// Logging
import {
  debugMCPSearchState,
  displayCorrelationTrace,
  displayLogResults,
  emergencyFixMCPSearch,
  generateStatusBadgeHtml,
  handlePerformanceAggregationChange,
  nextLogPage,
  previousLogPage,
  searchStructuredLogs,
  showAuditTrail,
  showCorrelationTrace,
  showLogDetails,
  showPerformanceMetrics,
  showSecurityEvents,
  testMCPSearchManually,
} from "./logging.js";

Admin.debugMCPSearchState = debugMCPSearchState;
Admin.displayCorrelationTrace = displayCorrelationTrace;
Admin.displayLogResults = displayLogResults;
Admin.emergencyFixMCPSearch = emergencyFixMCPSearch;
Admin.generateStatusBadgeHtml = generateStatusBadgeHtml;
Admin.handlePerformanceAggregationChange = handlePerformanceAggregationChange;
Admin.nextLogPage = nextLogPage;
Admin.previousLogPage = previousLogPage;
Admin.searchStructuredLogs = searchStructuredLogs;
Admin.showAuditTrail = showAuditTrail;
Admin.showCorrelationTrace = showCorrelationTrace;
Admin.showLogDetails = showLogDetails;
Admin.showPerformanceMetrics = showPerformanceMetrics;
Admin.showSecurityEvents = showSecurityEvents;
Admin.testMCPSearchManually = testMCPSearchManually;

// Metrics
import { retryLoadMetrics, switchTopPerformersTab } from "./metrics.js";

Admin.retryLoadMetrics = retryLoadMetrics;
Admin.switchTopPerformersTab = switchTopPerformersTab;

// Modals
import {
  closeApiKeyModal,
  closeModal,
  showApiKeyModal,
  submitApiKeyForm,
  toggleGrpcTlsFields,
  viewGrpcMethods,
} from "./modals.js";

Admin.closeApiKeyModal = closeApiKeyModal;
Admin.closeModal = closeModal;
Admin.showApiKeyModal = showApiKeyModal;
Admin.submitApiKeyForm = submitApiKeyForm;
Admin.toggleGrpcTlsFields = toggleGrpcTlsFields;
Admin.viewGrpcMethods = viewGrpcMethods;

// Plugins
import {
  closePluginDetails,
  filterByAuthor,
  filterByHook,
  filterByTag,
  filterPlugins,
  showPluginDetails,
} from "./plugins.js";

Admin.closePluginDetails = closePluginDetails;
Admin.filterByAuthor = filterByAuthor;
Admin.filterByHook = filterByHook;
Admin.filterByTag = filterByTag;
Admin.filterPlugins = filterPlugins;
Admin.showPluginDetails = showPluginDetails;

// Prompts
import { 
  editPrompt,
  initPromptSelect, 
  runPromptTest,
  testPrompt, 
  viewPrompt,
} from "./prompts.js";

Admin.editPrompt = editPrompt;
Admin.initPromptSelect = initPromptSelect;
Admin.runPromptTest = runPromptTest;
Admin.testPrompt = testPrompt;
Admin.viewPrompt = viewPrompt;

// Resources
import { 
  editResource,
  initResourceSelect,
  runResourceTest,
  testResource,
  viewResource,
} from "./resources.js";

Admin.editResource = editResource;
Admin.initResourceSelect = initResourceSelect;
Admin.runResourceTest = runResourceTest;
Admin.testResource = testResource;
Admin.viewResource = viewResource;

// Roots
import {
  viewRoot,
  editRoot,
  exportRoot,
} from "./roots.js";

Admin.viewRoot = viewRoot;
Admin.editRoot = editRoot;
Admin.exportRoot = exportRoot;

// Selective Import
import {
  handleSelectiveImport,
  resetImportSelection,
  selectAllItems,
  selectNoneItems,
  selectOnlyCustom,
  updateSelectionCount,
} from "./selectiveImport.js";

Admin.selectAllItems = selectAllItems;
Admin.selectNoneItems = selectNoneItems;
Admin.updateSelectionCount = updateSelectionCount;
Admin.selectOnlyCustom = selectOnlyCustom;
Admin.resetImportSelection = resetImportSelection;
Admin.handleSelectiveImport = handleSelectiveImport;

// Servers
import {
  viewServer,
  editServer,
} from "./servers.js"

Admin.viewServer = viewServer;
Admin.editServer = editServer;

// Tabs
import { showTab } from "./tabs.js";

Admin.showTab = showTab;

// Tags
import { clearTagFilter } from "./tags.js";

Admin.clearTagFilter = clearTagFilter;

// Teams
import {
  approveJoinRequest,
  dedupeSelectorItems,
  filterByRelationship,
  filterTeams,
  leaveTeam,
  rejectJoinRequest,
  requestToJoinTeam,
  serverSideTeamSearch,
  validatePasswordMatch,
  validatePasswordRequirements,
} from "./teams.js";

Admin.approveJoinRequest = approveJoinRequest;
Admin.dedupeSelectorItems = dedupeSelectorItems;
Admin.filterByRelationship = filterByRelationship;
Admin.filterTeams = filterTeams;
Admin.leaveTeam = leaveTeam;
Admin.rejectJoinRequest = rejectJoinRequest;
Admin.requestToJoinTeam = requestToJoinTeam;
Admin.serverSideTeamSearch = serverSideTeamSearch;
Admin.validatePasswordMatch = validatePasswordMatch;
Admin.validatePasswordRequirements = validatePasswordRequirements;

// Tokens
import { getAuthToken, getTeamNameById } from "./tokens.js";

Admin.getAuthToken = getAuthToken;
Admin.getTeamNameById = getTeamNameById;

// Tools
import {
  editTool,
  initToolSelect,
  testTool,
  enrichTool,
  generateToolTestCases,
  generateTestCases,
  validateTool,
  runToolTest,
  viewTool,
} from "./tools.js";

Admin.editTool = editTool;
Admin.initToolSelect = initToolSelect;
Admin.testTool = testTool;
Admin.enrichTool = enrichTool;
Admin.generateToolTestCases = generateToolTestCases;
Admin.generateTestCases = generateTestCases;
Admin.validateTool = validateTool;
Admin.runToolTest = runToolTest;
Admin.viewTool = viewTool;

// Users
import { hideUserEditModal } from "./users.js";

Admin.hideUserEditModal = hideUserEditModal;

// ===================================================================
// TIER 3 & 4: Domain and Orchestration modules (still using IIFE)
// These modules will attach their functions directly to window.Admin
// ===================================================================

// Import IIFE modules - they self-register on window.Admin
import "./app.js";
import "./events.js";

console.log("🚀 ContextForge MCP Gateway Admin API initialized");

// Export the Admin namespace so Vite's IIFE can expose it as window.Admin
export default Admin;
