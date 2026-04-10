import { OVERVIEW_DRILLDOWN_QUERY_KEYS } from "./constants";
import { safeReplaceState } from "./security";
import { resolveTabForNavigation, showTab } from "./tabs";
import { fetchWithAuth } from "./tokens";

export const mapOverviewRangeToHours = function (range) {
  switch ((range || "").toLowerCase()) {
    case "1h":
      return 1;
    case "6h":
      return 6;
    case "7d":
      return 168;
    case "24h":
    default:
      return 24;
  }
}

export const setOverviewDrilldownParams = function (state) {
  const url = new URL(window.location.href);
  OVERVIEW_DRILLDOWN_QUERY_KEYS.forEach((key) => {
    url.searchParams.delete(key);
  });

  if (state && state.timeRange) {
    url.searchParams.set("overview_time_range", state.timeRange);
  }
  if (state && state.entity) {
    url.searchParams.set("overview_entity", state.entity);
  }
  if (state && state.statusFilter) {
    url.searchParams.set("overview_status", state.statusFilter);
  }
  if (state && state.toolName) {
    url.searchParams.set("overview_tool_name", state.toolName);
  }
  if (state && state.viewMode) {
    url.searchParams.set("overview_view_mode", state.viewMode);
  }

  safeReplaceState({}, "", url.toString());
}

export const getOverviewDrilldownParams = function () {
  const url = new URL(window.location.href);
  const timeRange = url.searchParams.get("overview_time_range") || "";
  const entity = url.searchParams.get("overview_entity") || "";
  if (!timeRange && !entity) {
    return null;
  }

  return {
    timeRange: timeRange || "24h",
    entity,
    statusFilter: url.searchParams.get("overview_status") || "all",
    toolName: url.searchParams.get("overview_tool_name") || "",
    viewMode: url.searchParams.get("overview_view_mode") || "traces",
  };
}

export const getObservabilityController = function () {
  const container = document.querySelector(
    "#observability-panel .observability-container"
  );
  if (!container || !container.__x || !container.__x.$data) {
    return null;
  }
  return container.__x.$data;
}

export const applyOverviewDrilldownToObservability = function (drilldownState = null) {
  const state =
    drilldownState ||
    window.__pendingOverviewDrilldown ||
    getOverviewDrilldownParams();
  if (!state) {
    return false;
  }

  const controller = getObservabilityController();
  if (!controller) {
    return false;
  }

  controller.timeRange = state.timeRange || controller.timeRange || "24h";
  controller.statusFilter = state.statusFilter || "all";

  if (Object.prototype.hasOwnProperty.call(state, "toolName")) {
    controller.toolName = state.toolName || "";
  }

  const nextViewMode = state.viewMode || "traces";
  controller.viewMode = nextViewMode;
  if (
    nextViewMode === "metrics" &&
    typeof controller.loadMetricsView === "function"
  ) {
    controller.loadMetricsView();
  } else if (
    nextViewMode === "tools" &&
    typeof controller.loadToolsView === "function"
  ) {
    controller.loadToolsView();
  } else if (
    nextViewMode === "prompts" &&
    typeof controller.loadPromptsView === "function"
  ) {
    controller.loadPromptsView();
  } else if (
    nextViewMode === "resources" &&
    typeof controller.loadResourcesView === "function"
  ) {
    controller.loadResourcesView();
  }

  if (typeof controller.applyFilters === "function") {
    controller.applyFilters();
  }
  if (typeof controller.refreshStats === "function") {
    controller.refreshStats();
  }

  window.__pendingOverviewDrilldown = null;
  return true;
}

export const navigateOverviewDrilldown = function (drilldown = {}, selectedTimeRange = "24h") {
  const requestedTab = drilldown && drilldown.tab ? drilldown.tab : "overview";
  const resolvedTab = resolveTabForNavigation(requestedTab);
  if (!resolvedTab) {
    return "";
  }

  const state = {
    tab: resolvedTab,
    entity: drilldown.entity || "",
    timeRange: selectedTimeRange || "24h",
    statusFilter: drilldown.statusFilter || "all",
    toolName: drilldown.toolName || "",
    viewMode: drilldown.viewMode || "traces",
  };

  showTab(resolvedTab);
  setOverviewDrilldownParams(state);

  if (resolvedTab === "observability") {
    window.__pendingOverviewDrilldown = state;
    if (!applyOverviewDrilldownToObservability(state)) {
      let attempts = 0;
      const maxAttempts = 20;
      const timer = window.setInterval(() => {
        attempts += 1;
        if (
          applyOverviewDrilldownToObservability(state) ||
          attempts >= maxAttempts
        ) {
          window.clearInterval(timer);
        }
      }, 150);
    }
  }

  return resolvedTab;
}

export const overviewDashboard = function (payload = {}) {
  const initialNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
  const initialEdges = Array.isArray(payload.edges) ? payload.edges : [];
  const infrastructure = payload.infrastructure || {};

  return {
    flowNodes: initialNodes,
    flowEdges: initialEdges,
    topologyInfrastructure: {
      database: infrastructure.database || {
        label: "Database",
        status: "unknown",
        detail: "Unavailable",
      },
      cache: infrastructure.cache || {
        label: "Cache",
        status: "unknown",
        detail: "Unavailable",
      },
    },
    selectedTimeRange: payload.defaultTimeRange || "24h",
    lastUpdatedIso: payload.lastUpdatedIso || new Date().toISOString(),
    dataAgeSeconds:
      typeof payload.dataAgeSeconds === "number"
        ? payload.dataAgeSeconds
        : null,
    staleAfterSeconds:
      typeof payload.staleAfterSeconds === "number"
        ? payload.staleAfterSeconds
        : 300,
    isStale: Boolean(payload.isStale),
    announcement: "",

    init() {
      this.updateFreshnessState(false);
      if (window.__overviewFreshnessTimer) {
        window.clearInterval(window.__overviewFreshnessTimer);
      }
      window.__overviewFreshnessTimer = window.setInterval(() => {
        this.updateFreshnessState(true);
      }, 1000);

      this.refreshHealthSignals();
    },

    updateFreshnessState(announceTransition = true) {
      const wasStale = this.isStale;
      if (typeof this.dataAgeSeconds === "number") {
        this.dataAgeSeconds += 1;
      }
      this.isStale =
        this.dataAgeSeconds === null ||
        this.dataAgeSeconds > this.staleAfterSeconds;

      if (announceTransition && wasStale !== this.isStale) {
        this.announcement = this.isStale
          ? "Overview data is now stale."
          : "Overview data is fresh again.";
      }
    },

    freshnessLabel() {
      if (this.dataAgeSeconds === null) {
        return "No recent execution data";
      }
      if (this.isStale) {
        return `Stale (${this.dataAgeSeconds}s old)`;
      }
      return `Fresh (${this.dataAgeSeconds}s old)`;
    },

    freshnessBadgeClass() {
      if (this.dataAgeSeconds === null || this.isStale) {
        return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300";
      }
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300";
    },

    effectiveStatus(status) {
      if (this.isStale) {
        return "stale";
      }
      return status || "unknown";
    },

    healthLabel(status) {
      const normalized = this.effectiveStatus(status);
      if (normalized === "healthy") {
        return "Healthy";
      }
      if (normalized === "degraded") {
        return "Degraded";
      }
      if (normalized === "critical") {
        return "Critical";
      }
      if (normalized === "stale") {
        return "Stale";
      }
      return "Unknown";
    },

    healthBadgeClass(status) {
      const normalized = this.effectiveStatus(status);
      if (normalized === "healthy") {
        return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300";
      }
      if (normalized === "degraded") {
        return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300";
      }
      if (normalized === "critical") {
        return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300";
      }
      if (normalized === "stale") {
        return "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300";
      }
      return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200";
    },

    healthCardClass(status) {
      const normalized = this.effectiveStatus(status);
      if (normalized === "healthy") {
        return "border-emerald-200 bg-emerald-50/40 dark:border-emerald-800 dark:bg-emerald-900/10";
      }
      if (normalized === "degraded") {
        return "border-amber-200 bg-amber-50/40 dark:border-amber-800 dark:bg-amber-900/10";
      }
      if (normalized === "critical") {
        return "border-red-200 bg-red-50/40 dark:border-red-800 dark:bg-red-900/10";
      }
      if (normalized === "stale") {
        return "border-orange-200 bg-orange-50/40 dark:border-orange-800 dark:bg-orange-900/10";
      }
      return "border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800";
    },

    formatTimestamp(isoValue) {
      if (!isoValue) {
        return "n/a";
      }
      const date = new Date(isoValue);
      if (Number.isNaN(date.getTime())) {
        return "n/a";
      }
      return date.toLocaleString();
    },

    formatNumber(value) {
      const number = Number(value || 0);
      return Number.isFinite(number) ? number.toLocaleString() : "0";
    },

    formatRatio(active, total) {
      const activeValue = Number(active || 0);
      const totalValue = Number(total || 0);
      return `${activeValue.toLocaleString()}/${totalValue.toLocaleString()}`;
    },

    formatPercent(value) {
      const numeric = Number(value || 0);
      return `${numeric.toFixed(1)}%`;
    },

    formatLatency(value) {
      const numeric = Number(value || 0);
      if (!Number.isFinite(numeric) || numeric <= 0) {
        return "n/a";
      }
      return `${Math.round(numeric)}ms`;
    },

    nodeAriaLabel(node) {
      return `${node.title} node. Active ${node.active} of ${node.total}. Success ${this.formatPercent(node.successRate)}. Latency ${this.formatLatency(node.latencyMs)}.`;
    },

    edgeAriaLabel(edge) {
      return `${edge.title} flow. Throughput ${this.formatNumber(edge.throughput)}. Success ${this.formatPercent(edge.successRate)}. Latency ${this.formatLatency(edge.latencyMs)}.`;
    },

    announceTimeRangeChange() {
      this.announcement = `Drilldown range set to ${this.selectedTimeRange}.`;
      this.refreshHealthSignals();
    },

    deriveStatus(active, total, successRate, latencyMs) {
      if (this.isStale) {
        return "stale";
      }
      if (total > 0 && active <= 0) {
        return "critical";
      }
      if (successRate < 90 || latencyMs >= 1500) {
        return "critical";
      }
      if (successRate < 97 || latencyMs >= 800) {
        return "degraded";
      }
      if (total <= 0) {
        return "unknown";
      }
      return "healthy";
    },

    applyObservabilitySignals(successRate, latencyMs, totalRequests) {
      this.flowNodes.forEach((node) => {
        if (node.id === "core") {
          node.successRate = successRate;
          node.latencyMs = latencyMs;
          node.status = this.deriveStatus(
            Number(node.active || 0),
            Number(node.total || 0),
            successRate,
            latencyMs
          );
        }
      });

      this.flowEdges.forEach((edge) => {
        if (edge.id === "ingress-flow" || edge.id === "egress-flow") {
          edge.successRate = successRate;
          edge.latencyMs = latencyMs;
          edge.throughput = totalRequests;
          edge.status = this.deriveStatus(1, 1, successRate, latencyMs);
        }
      });
    },

    async refreshHealthSignals() {
      const hours = mapOverviewRangeToHours(this.selectedTimeRange);
      const intervalMinutes = Math.max(5, Math.round((hours * 60) / 24));
      const rootPath = window.ROOT_PATH || "";

      const timeseriesUrl = `${rootPath}/admin/observability/metrics/timeseries?hours=${hours}&interval_minutes=${intervalMinutes}`;
      const percentilesUrl = `${rootPath}/admin/observability/metrics/percentiles?hours=${hours}&interval_minutes=${intervalMinutes}`;

      try {
        const [timeseriesResponse, percentilesResponse] = await Promise.all([
          fetchWithAuth(timeseriesUrl, { method: "GET" }),
          fetchWithAuth(percentilesUrl, { method: "GET" }),
        ]);

        if (!timeseriesResponse.ok || !percentilesResponse.ok) {
          throw new Error("Unable to refresh observability metrics");
        }

        const timeseries = await timeseriesResponse.json();
        const percentiles = await percentilesResponse.json();

        const requestCount = (timeseries.request_count || []).reduce(
          (sum, value) => sum + Number(value || 0),
          0
        );
        const successCount = (timeseries.success_count || []).reduce(
          (sum, value) => sum + Number(value || 0),
          0
        );
        const successRate =
          requestCount > 0 ? (successCount / requestCount) * 100 : 100;

        const p90Values = (percentiles.p90 || []).filter((value) =>
          Number.isFinite(Number(value))
        );
        const latencyMs =
          p90Values.length > 0 ? Number(p90Values[p90Values.length - 1]) : 0;

        this.applyObservabilitySignals(successRate, latencyMs, requestCount);
        this.lastUpdatedIso = new Date().toISOString();
        this.dataAgeSeconds = 0;
        this.isStale = false;
        this.announcement = "Health signals refreshed.";
      } catch (error) {
        console.warn("Failed to refresh overview health signals:", error);
        this.announcement =
          "Health refresh failed. Showing the last known snapshot.";
      }
    },

    activateDrilldown(drilldown) {
      const target = drilldown || {};
      const resolvedTab = navigateOverviewDrilldown(
        target,
        this.selectedTimeRange
      );
      if (!resolvedTab) {
        return;
      }

      const entityLabel = target.entity || "selected signal";
      this.announcement = `Opened ${resolvedTab} diagnostics for ${entityLabel} using ${this.selectedTimeRange}.`;
    },
  };
};
