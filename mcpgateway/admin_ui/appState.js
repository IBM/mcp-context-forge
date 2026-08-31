// ===================================================================
// ENHANCED GLOBAL STATE MANAGEMENT
// ===================================================================

// Callback registry for cleanup functions defined in other modules
let cleanupToolTestStateCallback = null;

export function registerCleanupToolTestState(callback) {
  cleanupToolTestStateCallback = callback;
}

export const AppState = {
  parameterCount: 0,
  currentTestTool: null,
  toolTestResultEditor: null,
  isInitialized: false,
  pendingRequests: new Set(),
  currentTeamRelationshipFilter: "all",
  restrictedContextLogged: false,
  lastActivePaginationRoot: null,
  editors: {
    gateway: {
      headers: null,
      body: null,
      formHandler: null,
      closeHandler: null,
    },
  },
  // Pagination URL query state
  paginationQuerySetters: {},
  editServerSelections: {},

  // Debounce timers for member and non-member search
  memberSearchTimers: {},
  nonMemberSearchTimers: {},
  // Selection caches to preserve state across searches
  // nonMemberSelectionsCache: teamId -> {email: role}
  nonMemberSelectionsCache: {},
  // memberOverridesCache: teamId -> {email: {checked: bool, role: string}}
  memberOverridesCache: {},

  // Full model list for the model-id combobox (reset on each modal open)
  llmAllModels: [],
  llmModelsFetched: false,
  llmComboboxActiveIndex: -1,
  // Monotonic counter — each fetchModelsForModelModal call bumps it; stale
  // responses (from a prior call to the same or different provider) are discarded.
  llmFetchSeq: 0,

  // Track active modals to prevent multiple opens
  activeModals: new Set(),

  // Safe method to reset state
  reset() {
    this.parameterCount = 0;
    this.currentTestTool = null;
    this.toolTestResultEditor = null;
    this.activeModals.clear();
    this.restrictedContextLogged = false;

    // Cancel pending requests
    this.pendingRequests.forEach((controller) => {
      try {
        controller.abort();
      } catch (error) {
        console.warn("Error aborting request:", error);
      }
    });
    this.pendingRequests.clear();

    // Clean up editors
    Object.keys(this.editors.gateway).forEach((key) => {
      this.editors.gateway[key] = null;
    });

    // Clean up tool test state via registered callback
    if (typeof cleanupToolTestStateCallback === "function") {
      cleanupToolTestStateCallback();
    }

    this.paginationQuerySetters = {};
    this.editServerSelections = {};

    this.memberSearchTimers = {};
    this.nonMemberSearchTimers = {};
    this.nonMemberSelectionsCache = {};
    this.memberOverridesCache = {};

    this.llmAllModels = [];
    this.llmModelsFetched = false;
    this.llmComboboxActiveIndex = -1;
    this.llmFetchSeq = 0;

    console.log("✓ Application state reset");
  },

  // Track requests for cleanup
  addPendingRequest(controller) {
    this.pendingRequests.add(controller);
  },

  removePendingRequest(controller) {
    this.pendingRequests.delete(controller);
  },

  // Safe parameter count management
  getParameterCount() {
    return this.parameterCount;
  },

  incrementParameterCount() {
    return ++this.parameterCount;
  },

  decrementParameterCount() {
    if (this.parameterCount > 0) {
      return --this.parameterCount;
    }
    return 0;
  },

  // Modal management
  isModalActive(modalId) {
    return this.activeModals.has(modalId);
  },

  setModalActive(modalId) {
    this.activeModals.add(modalId);
  },

  setModalInactive(modalId) {
    this.activeModals.delete(modalId);
  },

  getCurrentTeamRelationshipFilter() {
    return this.currentTeamRelationshipFilter;
  },

  setCurrentTeamRelationshipFilter(teamRelationshipFilter) {
    this.currentTeamRelationshipFilter = teamRelationshipFilter;
  },

  // Restricted context tracking (sandboxed iframes)
  isRestrictedContextLogged() {
    return this.restrictedContextLogged;
  },

  setRestrictedContextLogged(value) {
    this.restrictedContextLogged = value;
  },

  getLastActivePaginationRoot() {
    return this.lastActivePaginationRoot;
  },

  setLastActivePaginationRoot(value) {
    this.lastActivePaginationRoot = value;
  },

  resetLlmModels() {
    this.llmAllModels = [];
  },
};
