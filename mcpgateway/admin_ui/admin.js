/* eslint-disable import-x/first */
/**
 * ====================================================================
 * ADMIN PUBLIC API - Facade for window.Admin namespace
 * ====================================================================
 *
 * This file imports all modules and exposes the public API to window.Admin
 * for use by HTMX and Alpine.js in templates.
 */

// Import HTMX and make it globally available
import htmx from 'htmx.org';
window.htmx = htmx;

// Bootstrap MUST be first - initializes window.Admin before any modules run
import "./bootstrap.js";

// Get reference to the Admin namespace
const Admin = window.Admin;

// ===================================================================
// TIER 1: Foundation modules (fully converted to ES modules)
// ===================================================================
// Utils
import {
  buildTableUrl,
  copyToClipboard,
  getPaginationParams,
  handleDeleteUserError,
  handleKeydown,
  isInactiveChecked,
  refreshLogs,
  safeGetElement,
  showErrorMessage,
  showNotification,
  showSuccessMessage,
} from "./utils.js";

Admin.buildTableUrl = buildTableUrl;
Admin.copyToClipboard = copyToClipboard;
Admin.getPaginationParams = getPaginationParams;
Admin.isInactiveChecked = isInactiveChecked;
Admin.handleDeleteUserError = handleDeleteUserError;
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

import { editA2AAgent, testA2AAgent, viewA2AAgent, toggleUAIDFields } from "./a2aAgents.js";

Admin.editA2AAgent = editA2AAgent;
Admin.testA2AAgent = testA2AAgent;
Admin.viewA2AAgent = viewA2AAgent;
Admin.toggleUAIDFields = toggleUAIDFields;

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
import {
  previewImport,
  resetImportFile,
  updateDropZoneStatus,
} from "./fileTransfer.js";

Admin.previewImport = previewImport;
Admin.resetImportFile = resetImportFile;
Admin.updateDropZoneStatus = updateDropZoneStatus;

// Filtering
import { filterServerTable, updateFilterStatus } from "./filters.js";

Admin.filterServerTable = filterServerTable;
Admin.updateFilterStatus = updateFilterStatus;

// Form Fields
import {
  performTeamSelectorSearch,
  searchTeamSelector,
  selectTeamFromSelector,
  updateRequestTypeOptions,
} from "./formFieldHandlers.js";

Admin.performTeamSelectorSearch = performTeamSelectorSearch;
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
import { editGateway, refreshGatewayTools, refreshToolsForSelectedGateways, testGateway, viewGateway } from "./gateways.js";

Admin.editGateway = editGateway;
Admin.refreshGatewayTools = refreshGatewayTools;
Admin.refreshToolsForSelectedGateways = refreshToolsForSelectedGateways;
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
  deleteLLMModel,
  deleteLLMProvider,
  editLLMModel,
  editLLMProvider,
  fetchLLMProviderModels,
  fetchModelsForModelModal,
  filterModelsByProvider,
  llmApiInfoApp,
  llmModelComboboxClose,
  llmModelComboboxFilter,
  llmModelComboboxKeydown,
  llmModelComboboxOpen,
  llmModelComboboxSelect,
  onLLMProviderTypeChange,
  onModelProviderChange,
  overviewDashboard,
  saveLLMModel,
  saveLLMProvider,
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
Admin.deleteLLMModel = deleteLLMModel;
Admin.deleteLLMProvider = deleteLLMProvider;
Admin.editLLMModel = editLLMModel;
Admin.editLLMProvider = editLLMProvider;
Admin.fetchLLMProviderModels = fetchLLMProviderModels;
Admin.fetchModelsForModelModal = fetchModelsForModelModal;
Admin.filterModelsByProvider = filterModelsByProvider;
Admin.llmApiInfoApp = llmApiInfoApp;
Admin.llmModelComboboxClose = llmModelComboboxClose;
Admin.llmModelComboboxFilter = llmModelComboboxFilter;
Admin.llmModelComboboxKeydown = llmModelComboboxKeydown;
Admin.llmModelComboboxOpen = llmModelComboboxOpen;
Admin.llmModelComboboxSelect = llmModelComboboxSelect;
Admin.onLLMProviderTypeChange = onLLMProviderTypeChange;
Admin.onModelProviderChange = onModelProviderChange;
Admin.overviewDashboard = overviewDashboard;
Admin.saveLLMModel = saveLLMModel;
Admin.saveLLMProvider = saveLLMProvider;
Admin.showAddModelModal = showAddModelModal;
Admin.showAddProviderModal = showAddProviderModal;
Admin.switchLLMSettingsTab = switchLLMSettingsTab;
Admin.syncLLMProviderModels = syncLLMProviderModels;
Admin.toggleLLMModel = toggleLLMModel;
Admin.toggleLLMProvider = toggleLLMProvider;

// Logging
import {
  debugMCPSearchState,
  displayAuditTrail,
  displayCorrelationTrace,
  displayLogResults,
  displaySecurityEvents,
  downloadLogFile,
  generateStatusBadgeHtml,
  handlePerformanceAggregationChange,
  nextLogPage,
  previousLogPage,
  restoreLogTableHeaders,
  searchStructuredLogs,
  showAuditTrail,
  showCorrelationTrace,
  showLogDetails,
  showPerformanceMetrics,
  showSecurityEvents,
  testMCPSearchManually,
} from "./logging.js";

Admin.debugMCPSearchState = debugMCPSearchState;
Admin.displayAuditTrail = displayAuditTrail;
Admin.displayCorrelationTrace = displayCorrelationTrace;
Admin.displayLogResults = displayLogResults;
Admin.displaySecurityEvents = displaySecurityEvents;
Admin.downloadLogFile = downloadLogFile;
Admin.generateStatusBadgeHtml = generateStatusBadgeHtml;
Admin.handlePerformanceAggregationChange = handlePerformanceAggregationChange;
Admin.nextLogPage = nextLogPage;
Admin.previousLogPage = previousLogPage;
Admin.restoreLogTableHeaders = restoreLogTableHeaders;
Admin.searchStructuredLogs = searchStructuredLogs;
Admin.showAuditTrail = showAuditTrail;
Admin.showCorrelationTrace = showCorrelationTrace;
Admin.showLogDetails = showLogDetails;
Admin.showPerformanceMetrics = showPerformanceMetrics;
Admin.showSecurityEvents = showSecurityEvents;
Admin.testMCPSearchManually = testMCPSearchManually;

// Metrics
import {
  retryLoadMetrics,
  switchTopPerformersTab,
  showMetricsError,
  displayMetrics,
  loadAggregatedMetrics,
} from "./metrics.js";

Admin.retryLoadMetrics = retryLoadMetrics;
Admin.switchTopPerformersTab = switchTopPerformersTab;
Admin.showMetricsError = showMetricsError;
Admin.displayMetrics = displayMetrics;
Admin.loadAggregatedMetrics = loadAggregatedMetrics;

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

// Navigation
import { navigateAdmin } from "./navigation.js";

Admin.navigateAdmin = navigateAdmin;

// Pagination
import { paginationData } from "./pagination.js";

Admin.paginationData = paginationData;

// Alpine components
import { overflowMenu } from "./components/overflow-menu.js";

Admin.overflowMenu = overflowMenu;

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
import { viewRoot, editRoot, exportRoot } from "./roots.js";

Admin.viewRoot = viewRoot;
Admin.editRoot = editRoot;
Admin.exportRoot = exportRoot;

// Search
import {
  clearSearch,
  closeGlobalSearchModal,
  debouncedMemberSearch,
  debouncedNonMemberSearch,
  navigateToGlobalSearchResult,
  openGlobalSearchModal,
  serverSideMemberSearch,
} from "./search.js";

Admin.clearSearch = clearSearch;
Admin.closeGlobalSearchModal = closeGlobalSearchModal;
Admin.debouncedMemberSearch = debouncedMemberSearch;
Admin.debouncedNonMemberSearch = debouncedNonMemberSearch;
Admin.navigateToGlobalSearchResult = navigateToGlobalSearchResult;
Admin.openGlobalSearchModal = openGlobalSearchModal;
Admin.serverSideMemberSearch = serverSideMemberSearch;

// Selective Import
import {
  displayImportPreview,
  handleSelectiveImport,
  resetImportSelection,
  selectAllItems,
  selectNoneItems,
  selectOnlyCustom,
  updateSelectionCount,
} from "./selectiveImport.js";

Admin.displayImportPreview = displayImportPreview;
Admin.selectAllItems = selectAllItems;
Admin.selectNoneItems = selectNoneItems;
Admin.updateSelectionCount = updateSelectionCount;
Admin.selectOnlyCustom = selectOnlyCustom;
Admin.resetImportSelection = resetImportSelection;
Admin.handleSelectiveImport = handleSelectiveImport;

// Servers
import { viewServer, editServer } from "./servers.js";

Admin.viewServer = viewServer;
Admin.editServer = editServer;

// Tabs
import { showTab } from "./tabs.js";

Admin.showTab = showTab;

// Tags
import { clearTagFilter, updateFilterEmptyState } from "./tags.js";

Admin.clearTagFilter = clearTagFilter;
Admin.updateFilterEmptyState = updateFilterEmptyState;

// Teams
import {
  approveJoinRequest,
  dedupeSelectorItems,
  displayPublicTeams,
  filterByRelationship,
  filterTeams,
  hideTeamEditModal,
  leaveTeam,
  loadTeamSelectorDropdown,
  rejectJoinRequest,
  requestToJoinTeam,
  serverSideTeamSearch,
  updateDefaultVisibility,
  validatePasswordMatch,
  validatePasswordRequirements,
} from "./teams.js";

Admin.approveJoinRequest = approveJoinRequest;
Admin.dedupeSelectorItems = dedupeSelectorItems;
Admin.displayPublicTeams = displayPublicTeams;
Admin.filterByRelationship = filterByRelationship;
Admin.filterTeams = filterTeams;
Admin.hideTeamEditModal = hideTeamEditModal;
Admin.leaveTeam = leaveTeam;
Admin.loadTeamSelectorDropdown = loadTeamSelectorDropdown;
Admin.rejectJoinRequest = rejectJoinRequest;
Admin.requestToJoinTeam = requestToJoinTeam;
Admin.serverSideTeamSearch = serverSideTeamSearch;
Admin.updateDefaultVisibility = updateDefaultVisibility;
Admin.validatePasswordMatch = validatePasswordMatch;
Admin.validatePasswordRequirements = validatePasswordRequirements;

// Tokens
import {
  getAuthToken,
  getTeamNameById,
  loadTokensList,
  setupCreateTokenForm,
  showTokenDetailsModal,
  showUsageStatsModal,
} from "./tokens.js";

Admin.getAuthToken = getAuthToken;
Admin.getTeamNameById = getTeamNameById;
Admin.loadTokensList = loadTokensList;
Admin.setupCreateTokenForm = setupCreateTokenForm;
Admin.showTokenDetailsModal = showTokenDetailsModal;
Admin.showUsageStatsModal = showUsageStatsModal;

// Tools
import {
  editTool,
  initToolSelect,
  invokeTool,
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
Admin.invokeTool = invokeTool;
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

console.log("🚀 ContextForge AI Gateway Admin API initialized");

// Export the Admin namespace so Vite's IIFE can expose it as window.Admin
export default Admin;
