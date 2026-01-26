((Admin) => {
    // ===================================================================
    // ENHANCED METRICS LOADING with Retry Logic and Request Deduplication
    // ===================================================================

    // More robust metrics request tracking
    let metricsRequestController = null;
    let metricsRequestPromise = null;
    const MAX_METRICS_RETRIES = 3; // Increased from 2
    const METRICS_RETRY_DELAY = 2000; // Increased from 1500ms

    /**
    * Enhanced metrics loading with better race condition prevention
    */
    Admin.loadAggregatedMetrics = async function () {
        const metricsPanel = Admin.safeGetElement("metrics-panel", true);
        if (!metricsPanel || metricsPanel.closest(".tab-panel.hidden")) {
            console.log("Metrics panel not visible, skipping load");
            return;
        }

        // Cancel any existing request
        if (metricsRequestController) {
            console.log("Cancelling existing metrics request...");
            metricsRequestController.abort();
            metricsRequestController = null;
        }

        // If there's already a promise in progress, return it
        if (metricsRequestPromise) {
            console.log("Returning existing metrics promise...");
            return metricsRequestPromise;
        }

        console.log("Starting new metrics request...");
        Admin.showMetricsLoading();

        metricsRequestPromise = Admin.loadMetricsInternal().finally(() => {
            metricsRequestPromise = null;
            metricsRequestController = null;
            Admin.hideMetricsLoading();
        });

        return metricsRequestPromise;
    };

    Admin.loadMetricsInternal = async function () {
        try {
            console.log("Loading aggregated metrics...");
            Admin.showMetricsLoading();

            const result = await Admin.fetchWithTimeoutAndRetry(
                `${window.ROOT_PATH}/admin/metrics`,
                {}, // options
                (window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000) * 1.5, // Use 1.5x configurable timeout for metrics
                MAX_METRICS_RETRIES,
            );

            if (!result.ok) {
                // If metrics endpoint doesn't exist, show a placeholder instead of failing
                if (result.status === 404) {
                    Admin.showMetricsPlaceholder();
                    return;
                }
                // FIX: Handle 500 errors specifically
                if (result.status >= 500) {
                    throw new Error(
                        `Server error (${result.status}). The metrics calculation may have failed.`,
                    );
                }
                throw new Error(`HTTP ${result.status}: ${result.statusText}`);
            }

            // FIX: Handle empty or invalid JSON responses
            let data;
            try {
                const text = await result.text();
                if (!text || !text.trim()) {
                    console.warn("Empty metrics response, using default data");
                    data = {}; // Use empty object as fallback
                } else {
                    data = JSON.parse(text);
                }
            } catch (parseError) {
                console.error("Failed to parse metrics JSON:", parseError);
                data = {}; // Use empty object as fallback
            }

            console.log("Metrics data received:", data);
            Admin.displayMetrics(data);
            console.log("✓ Metrics loaded successfully");
        } catch (error) {
            console.error("Error loading aggregated metrics:", error);
            Admin.showMetricsError(error);
        } finally {
            Admin.hideMetricsLoading();
        }
    };

    /**
    * Enhanced fetch with automatic retry logic and better error handling
    */
    Admin.fetchWithTimeoutAndRetry = async function (
        url,
        options = {},
        timeout = window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
        maxRetries = 3,
    ) {
        let lastError;

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                console.log(`Metrics fetch attempt ${attempt}/${maxRetries}`);

                // Create new controller for each attempt
                metricsRequestController = new AbortController();

                const response = await Admin.fetchWithTimeout(
                    url,
                    {
                        ...options,
                        signal: metricsRequestController.signal,
                    },
                    timeout,
                );

                console.log(`✓ Metrics fetch attempt ${attempt} succeeded`);
                return response;
            } catch (error) {
                lastError = error;

                console.warn(
                    `✗ Metrics fetch attempt ${attempt} failed:`,
                    error.message,
                );

                // Don't retry on certain errors
                if (error.name === "AbortError" && attempt < maxRetries) {
                    console.log("Request was aborted, skipping retry");
                    throw error;
                }

                // Don't retry on the last attempt
                if (attempt === maxRetries) {
                    console.error(
                        `All ${maxRetries} metrics fetch attempts failed`,
                    );
                    throw error;
                }

                // Wait before retrying, with modest backoff
                const delay = METRICS_RETRY_DELAY * attempt;
                console.log(`Retrying metrics fetch in ${delay}ms...`);
                await new Promise((resolve) => setTimeout(resolve, delay));
            }
        }

        throw lastError;
    };

    /**
    * Show loading state for metrics
    */
    Admin.showMetricsLoading = function () {
        // Only clear the aggregated metrics section, not the entire panel (to preserve System Metrics)
        const aggregatedSection = Admin.safeGetElement(
            "aggregated-metrics-section",
            true,
        );
        if (aggregatedSection) {
            const existingLoading = Admin.safeGetElement("metrics-loading", true);
            if (existingLoading) {
                return;
            }

            const loadingDiv = document.createElement("div");
            loadingDiv.id = "metrics-loading";
            loadingDiv.className = "flex justify-center items-center p-8";
            loadingDiv.innerHTML = `
                <div class="text-center">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
                    <p class="text-gray-600">Loading aggregated metrics...</p>
                    <p class="text-sm text-gray-500 mt-2">This may take a moment</p>
                </div>
            `;
            aggregatedSection.innerHTML = "";
            aggregatedSection.appendChild(loadingDiv);
        }
    };

    /**
    * Hide loading state for metrics
    */
    Admin.hideMetricsLoading = function () {
        const loadingDiv = Admin.safeGetElement("metrics-loading", true);
        if (loadingDiv && loadingDiv.parentNode) {
            loadingDiv.parentNode.removeChild(loadingDiv);
        }
    };

    /**
    * Enhanced error display with retry option
    */
    Admin.showMetricsError = function (error) {
        // Only show error in the aggregated metrics section, not the entire panel
        const aggregatedSection = Admin.safeGetElement("aggregated-metrics-content");
        if (aggregatedSection) {
            const errorDiv = document.createElement("div");
            errorDiv.className = "text-center p-8";

            const errorMessage = Admin.handleFetchError(error, "load metrics");

            // Determine if this looks like a server/network issue
            const isNetworkError =
                error.message.includes("fetch") ||
                error.message.includes("network") ||
                error.message.includes("timeout") ||
                error.name === "AbortError";

            const helpText = isNetworkError
                ? "This usually happens when the server is slow to respond or there's a network issue."
                : "There may be an issue with the metrics calculation on the server.";

            errorDiv.innerHTML = `
                <div class="text-red-600 mb-4">
                    <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <h3 class="text-lg font-medium mb-2">Failed to Load Aggregated Metrics</h3>
                    <p class="text-sm mb-2">${escapeHtml(errorMessage)}</p>
                    <p class="text-xs text-gray-500 mb-4">${helpText}</p>
                    <button
                        onclick="Admin.retryLoadMetrics()"
                        class="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition-colors">
                        Try Again
                    </button>
                </div>
            `;

            aggregatedSection.innerHTML = "";
            aggregatedSection.appendChild(errorDiv);
        }
    };

    /**
    * Retry loading metrics (callable from retry button)
    */
    Admin.retryLoadMetrics = function () {
        console.log("Manual retry requested");
        // Reset all tracking variables
        metricsRequestController = null;
        metricsRequestPromise = null;
        Admin.loadAggregatedMetrics();
    };

    Admin.showMetricsPlaceholder = function () {
        const aggregatedSection = Admin.safeGetElement("aggregated-metrics-section");
        if (aggregatedSection) {
            const placeholderDiv = document.createElement("div");
            placeholderDiv.className = "text-gray-600 p-4 text-center";
            placeholderDiv.textContent =
                "Aggregated metrics endpoint not available. This feature may not be implemented yet.";
            aggregatedSection.innerHTML = "";
            aggregatedSection.appendChild(placeholderDiv);
        }
    };

    // ===================================================================
    // ENHANCED METRICS DISPLAY with Complete System Overview
    // ===================================================================

    Admin.displayMetrics = function (data, retryCount = 0) {
        console.log("displayMetrics called with:", data, "retry:", retryCount);

        // Ensure parent sections exist, create container if missing
        const metricsPanel = Admin.safeGetElement("metrics-panel");
        const aggregatedSection = Admin.safeGetElement(
            "aggregated-metrics-section",
        );
        let aggregatedContent = Admin.safeGetElement(
            "aggregated-metrics-content",
        );

        console.log("Panel check:", {
            metricsPanel: !!metricsPanel,
            metricsPanelHidden: metricsPanel?.classList.contains("hidden"),
            aggregatedSection: !!aggregatedSection,
            aggregatedContent: !!aggregatedContent,
        });

        if (!aggregatedSection) {
            if (retryCount < 10) {
                console.error(
                    `Aggregated metrics section missing, retrying (${retryCount + 1}/10) in 100ms`,
                );
                setTimeout(() => Admin.displayMetrics(data, retryCount + 1), 100);
                return;
            }
            console.error(
                "Aggregated metrics section not found after retries; cannot render metrics",
            );
            return;
        }

        if (!aggregatedContent) {
            console.warn(
                "Aggregated metrics content container missing; creating fallback container",
            );
            aggregatedContent = document.createElement("div");
            aggregatedContent.id = "aggregated-metrics-content";
            aggregatedContent.className =
                "overflow-auto mb-6 bg-gray-100 dark:bg-gray-900";

            // Insert before chart if present, otherwise append to section
            const chartElement = aggregatedSection.querySelector("#metricsChart");
            if (chartElement && chartElement.parentElement === aggregatedSection) {
                aggregatedSection.insertBefore(aggregatedContent, chartElement);
            } else {
                aggregatedSection.appendChild(aggregatedContent);
            }
        }

        console.log("aggregated-metrics-content element ready:", aggregatedContent);

        try {
            // FIX: Handle completely empty data
            if (!data || Object.keys(data).length === 0) {
                console.warn("Empty or null data received");
                const emptyStateDiv = document.createElement("div");
                emptyStateDiv.className = "text-center p-8 text-gray-500";
                emptyStateDiv.innerHTML = `
                    <svg class="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                    </svg>
                    <h3 class="text-lg font-medium mb-2">No Metrics Available</h3>
                    <p class="text-sm">Metrics data will appear here once tools, resources, or prompts are executed.</p>
                    <button onclick="Admin.retryLoadMetrics()" class="mt-4 bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 transition-colors">
                        Refresh Metrics
                    </button>
                `;
                aggregatedContent.innerHTML = "";
                aggregatedContent.appendChild(emptyStateDiv);
                return;
            }

            // Create main container with safe structure
            const mainContainer = document.createElement("div");
            mainContainer.className = "space-y-6";

            // Key Performance Indicators section - render to dedicated container above Top Performers
            const kpiData = Admin.extractKPIData(data);
            if (Object.keys(kpiData).length > 0) {
                const kpiContainer = Admin.safeGetElement("kpi-metrics-section");
                if (kpiContainer) {
                    const kpiSection = Admin.createKPISection(kpiData);
                    kpiContainer.innerHTML = "";
                    kpiContainer.appendChild(kpiSection);
                }
            }

            // Top Performers are now handled entirely by HTMX sections below aggregated-metrics-content
            // (see <details> sections with top-tools-content, top-resources-content, etc. in admin.html)
            // Legacy JavaScript widget is disabled to prevent duplicate rendering
            console.log(
                "✓ Top Performers handled by HTMX - skipping legacy JavaScript widget",
            );

            // Individual metrics grid - render inside Top Performers section
            const individualMetricsGrid = Admin.safeGetElement(
                "individual-metrics-grid",
            );
            if (individualMetricsGrid) {
                const metricsContainer = document.createElement("div");
                metricsContainer.className =
                    "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6";

                // Tools metrics
                if (data.tools) {
                    const toolsCard = Admin.createMetricsCard("Tools", data.tools);
                    metricsContainer.appendChild(toolsCard);
                }

                // Resources metrics
                if (data.resources) {
                    const resourcesCard = Admin.createMetricsCard(
                        "Resources",
                        data.resources,
                    );
                    metricsContainer.appendChild(resourcesCard);
                }

                // Prompts metrics
                if (data.prompts) {
                    const promptsCard = Admin.createMetricsCard("Prompts", data.prompts);
                    metricsContainer.appendChild(promptsCard);
                }

                // Gateways metrics
                if (data.gateways) {
                    const gatewaysCard = Admin.createMetricsCard(
                        "Gateways",
                        data.gateways,
                    );
                    metricsContainer.appendChild(gatewaysCard);
                }

                // Servers metrics
                if (data.servers) {
                    const serversCard = Admin.createMetricsCard("Servers", data.servers);
                    metricsContainer.appendChild(serversCard);
                }

                // Performance metrics
                if (data.performance) {
                    const performanceCard = Admin.createPerformanceCard(data.performance);
                    metricsContainer.appendChild(performanceCard);
                }

                individualMetricsGrid.innerHTML = "";
                individualMetricsGrid.appendChild(metricsContainer);
            }

            // Recent activity section (bottom)
            if (data.recentActivity || data.recent) {
                const activityData = data.recentActivity || data.recent;
                const activitySection = Admin.createRecentActivitySection(activityData);
                mainContainer.appendChild(activitySection);
            }

            // Safe content replacement
            aggregatedContent.innerHTML = "";
            aggregatedContent.appendChild(mainContainer);

            console.log("✓ Enhanced metrics display rendered successfully");
        } catch (error) {
            console.error("Error displaying metrics:", error);
            Admin.showMetricsError(error);
        }
    };

    /**
    * Switch between Top Performers tabs
    */
    // eslint-disable-next-line no-unused-vars
    Admin.switchTopPerformersTab = function (entityType) {
        // Hide all panels
        const panels = document.querySelectorAll(".top-performers-panel");
        panels.forEach((panel) => panel.classList.add("hidden"));

        // Remove active state from all tabs
        const tabs = document.querySelectorAll(".top-performers-tab");
        tabs.forEach((tab) => {
            tab.classList.remove(
                "border-indigo-500",
                "text-indigo-600",
                "dark:text-indigo-400",
            );
            tab.classList.add(
                "border-transparent",
                "text-gray-500",
                "hover:text-gray-700",
                "hover:border-gray-300",
                "dark:text-gray-400",
                "dark:hover:text-gray-300",
            );
        });

        // Show selected panel
        const selectedPanel = Admin.safeGetElement(
            `top-performers-panel-${entityType}`,
        );
        if (selectedPanel) {
            selectedPanel.classList.remove("hidden");
        }

        // Activate selected tab
        const selectedTab = Admin.safeGetElement(
            `top-performers-tab-${entityType}`,
        );
        if (selectedTab) {
            selectedTab.classList.remove(
                "border-transparent",
                "text-gray-500",
                "hover:text-gray-700",
                "hover:border-gray-300",
                "dark:text-gray-400",
                "dark:hover:text-gray-300",
            );
            selectedTab.classList.add(
                "border-indigo-500",
                "text-indigo-600",
                "dark:text-indigo-400",
            );
        }
    };

    /**
    * SECURITY: Create system summary card with safe HTML generation
    */
    // eslint-disable-next-line no-unused-vars
    Admin.createSystemSummaryCard = function (systemData) {
        try {
            const card = document.createElement("div");
            card.className =
                "bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg shadow-lg p-6 text-white";

            // Card title
            const title = document.createElement("h2");
            title.className = "text-2xl font-bold mb-4";
            title.textContent = "System Overview";
            card.appendChild(title);

            // Statistics grid
            const statsGrid = document.createElement("div");
            statsGrid.className = "grid grid-cols-2 md:grid-cols-4 gap-4";

            // Define system statistics with validation
            const systemStats = [
                {
                    key: "uptime",
                    label: "Uptime",
                    suffix: "",
                },
                {
                    key: "totalRequests",
                    label: "Total Requests",
                    suffix: "",
                },
                {
                    key: "activeConnections",
                    label: "Active Connections",
                    suffix: "",
                },
                {
                    key: "memoryUsage",
                    label: "Memory Usage",
                    suffix: "%",
                },
                {
                    key: "cpuUsage",
                    label: "CPU Usage",
                    suffix: "%",
                },
                {
                    key: "diskUsage",
                    label: "Disk Usage",
                    suffix: "%",
                },
                {
                    key: "networkIn",
                    label: "Network In",
                    suffix: " MB",
                },
                {
                    key: "networkOut",
                    label: "Network Out",
                    suffix: " MB",
                },
            ];

            systemStats.forEach((stat) => {
                const value =
                    systemData[stat.key] ??
                    systemData[stat.key.replace(/([A-Z])/g, "_$1").toLowerCase()] ??
                    "N/A";

                const statDiv = document.createElement("div");
                statDiv.className = "text-center";

                const valueSpan = document.createElement("div");
                valueSpan.className = "text-2xl font-bold";
                valueSpan.textContent =
                    (value === "N/A" ? "N/A" : String(value)) + stat.suffix;

                const labelSpan = document.createElement("div");
                labelSpan.className = "text-blue-100 text-sm";
                labelSpan.textContent = stat.label;

                statDiv.appendChild(valueSpan);
                statDiv.appendChild(labelSpan);
                statsGrid.appendChild(statDiv);
            });

            card.appendChild(statsGrid);
            return card;
        } catch (error) {
            console.error("Error creating system summary card:", error);
            return document.createElement("div"); // Safe fallback
        }
    };

    /**
    * SECURITY: Create KPI section with safe data handling
    */
    Admin.createKPISection = function (kpiData) {
        try {
            const section = document.createElement("div");
            section.className = "grid grid-cols-1 md:grid-cols-4 gap-4";

            const kpis = [
                {
                    key: "totalExecutions",
                    label: "Total Executions",
                    icon: "🎯",
                    color: "blue",
                },
                {
                    key: "successRate",
                    label: "Success Rate",
                    icon: "✅",
                    color: "green",
                },
                {
                    key: "avgResponseTime",
                    label: "Avg Response Time",
                    icon: "⚡",
                    color: "yellow",
                },
                { key: "errorRate", label: "Error Rate", icon: "❌", color: "red" },
            ];

            kpis.forEach((kpi) => {
                let value = kpiData[kpi.key];
                if (value === null || value === undefined || value === "N/A") {
                    value = "N/A";
                } else {
                    if (kpi.key === "avgResponseTime") {
                        // ensure numeric then 3 decimals + unit
                        value = Admin.isNaN(Number(value))
                            ? "N/A"
                            : Admin.Number(value).toFixed(3) + " ms";
                    } else if (
                        kpi.key === "successRate" ||
                        kpi.key === "errorRate"
                    ) {
                        value = String(value) + "%";
                    } else {
                        value = String(value);
                    }
                }

                const kpiCard = document.createElement("div");
                kpiCard.className = `bg-white rounded-lg shadow p-4 border-l-4 border-${kpi.color}-500 dark:bg-gray-800`;

                const header = document.createElement("div");
                header.className = "flex items-center justify-between";

                const iconSpan = document.createElement("span");
                iconSpan.className = "text-2xl";
                iconSpan.textContent = kpi.icon;

                const valueDiv = document.createElement("div");
                valueDiv.className = "text-right";

                const valueSpan = document.createElement("div");
                valueSpan.className = `text-2xl font-bold text-${kpi.color}-600`;
                valueSpan.textContent = value;

                const labelSpan = document.createElement("div");
                labelSpan.className = "text-sm text-gray-500 dark:text-gray-400";
                labelSpan.textContent = kpi.label;

                valueDiv.appendChild(valueSpan);
                valueDiv.appendChild(labelSpan);
                header.appendChild(iconSpan);
                header.appendChild(valueDiv);
                kpiCard.appendChild(header);
                section.appendChild(kpiCard);
            });

            return section;
        } catch (err) {
            console.error("Error creating KPI section:", err);
            return document.createElement("div");
        }
    };

    /**
    * SECURITY: Extract and calculate KPI data with validation
    */
    Admin.formatValue = function (value, key) {
        if (value === null || value === undefined || value === "N/A") {
            return "N/A";
        }

        if (key === "avgResponseTime") {
            return Admin.isNaN(Number(value)) ? "N/A" : Admin.Number(value).toFixed(3) + " ms";
        }

        if (key === "successRate" || key === "errorRate") {
            return `${value}%`;
        }

        if (typeof value === "number" && Number.isNaN(value)) {
            return "N/A";
        }

        return String(value).trim() === "" ? "N/A" : String(value);
    };

    Admin.extractKPIData = function (data) {
        try {
            let totalExecutions = 0;
            let totalSuccessful = 0;
            let totalFailed = 0;
            let weightedResponseSum = 0;

            const categoryKeys = [
                ["tools", "Tools Metrics", "Tools", "tools_metrics"],
                [
                    "resources",
                    "Resources Metrics",
                    "Resources",
                    "resources_metrics",
                ],
                ["prompts", "Prompts Metrics", "Prompts", "prompts_metrics"],
                ["servers", "Servers Metrics", "Servers", "servers_metrics"],
                ["gateways", "Gateways Metrics", "Gateways", "gateways_metrics"],
                [
                    "virtualServers",
                    "Virtual Servers",
                    "VirtualServers",
                    "virtual_servers",
                ],
            ];

            categoryKeys.forEach((aliases) => {
                let categoryData = null;
                for (const key of aliases) {
                    if (data && data[key]) {
                        categoryData = data[key];
                        break;
                    }
                }
                if (!categoryData) {
                    return;
                }

                // Build a lowercase-key map so "Successful Executions" and "successfulExecutions" both match
                const normalized = {};
                Object.entries(categoryData).forEach(([k, v]) => {
                    normalized[k.toString().trim().toLowerCase()] = v;
                });

                const executions = Admin.Number(
                    normalized["total executions"] ??
                        normalized.totalexecutions ??
                        normalized.execution_count ??
                        normalized["execution-count"] ??
                        normalized.executions ??
                        normalized.total_executions ??
                        0,
                );

                const successful = Admin.Number(
                    normalized["successful executions"] ??
                        normalized.successfulexecutions ??
                        normalized.successful ??
                        normalized.successful_executions ??
                        0,
                );

                const failed = Admin.Number(
                    normalized["failed executions"] ??
                        normalized.failedexecutions ??
                        normalized.failed ??
                        normalized.failed_executions ??
                        0,
                );

                const avgResponseRaw =
                    normalized["average response time"] ??
                    normalized.avgresponsetime ??
                    normalized.avg_response_time ??
                    normalized.avgresponsetime ??
                    null;

                totalExecutions += Number.isNaN(executions) ? 0 : executions;
                totalSuccessful += Number.isNaN(successful) ? 0 : successful;
                totalFailed += Number.isNaN(failed) ? 0 : failed;

                if (
                    avgResponseRaw !== null &&
                    avgResponseRaw !== undefined &&
                    avgResponseRaw !== "N/A" &&
                    !Number.isNaN(Admin.Number(avgResponseRaw)) &&
                    executions > 0
                ) {
                    weightedResponseSum += executions * Admin.Number(avgResponseRaw);
                }
            });

            const avgResponseTime =
                totalExecutions > 0 && weightedResponseSum > 0
                    ? weightedResponseSum / totalExecutions
                    : null;

            const successRate =
                totalExecutions > 0
                    ? Math.round((totalSuccessful / totalExecutions) * 100)
                    : 0;

            const errorRate =
                totalExecutions > 0
                    ? Math.round((totalFailed / totalExecutions) * 100)
                    : 0;

            // Debug: show what we've read from the payload
            console.log("KPI Totals:", {
                totalExecutions,
                totalSuccessful,
                totalFailed,
                successRate,
                errorRate,
                avgResponseTime,
            });

            return { totalExecutions, successRate, errorRate, avgResponseTime };
        } catch (err) {
            console.error("Error extracting KPI data:", err);
            return {
                totalExecutions: 0,
                successRate: 0,
                errorRate: 0,
                avgResponseTime: null,
            };
        }
    };

    // eslint-disable-next-line no-unused-vars
    Admin.updateKPICards = function (kpiData) {
        try {
            if (!kpiData) {
                return;
            }

            const idMap = {
                "metrics-total-executions": Admin.formatValue(
                    kpiData.totalExecutions,
                    "totalExecutions",
                ),
                "metrics-success-rate": Admin.formatValue(
                    kpiData.successRate,
                    "successRate",
                ),
                "metrics-avg-response-time": Admin.formatValue(
                    kpiData.avgResponseTime,
                    "avgResponseTime",
                ),
                "metrics-error-rate": Admin.formatValue(kpiData.errorRate, "errorRate"),
            };

            Object.entries(idMap).forEach(([id, value]) => {
                const el = Admin.safeGetElement(id);
                if (!el) {
                    return;
                }

                // If card has a `.value` span inside, update it, else update directly
                const valueEl =
                    el.querySelector?.(".value") ||
                    el.querySelector?.(".kpi-value");
                if (valueEl) {
                    valueEl.textContent = value;
                } else {
                    el.textContent = value;
                }
            });
        } catch (err) {
            console.error("updateKPICards error:", err);
        }
    };

    /**
    * SECURITY: Create top performers section with safe display
    */
    // Admin.createTopPerformersSection = function (topData) {
    //     try {
    //         const section = document.createElement("div");
    //         section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

    //         const title = document.createElement("h3");
    //         title.className = "text-lg font-medium mb-4 dark:text-gray-200";
    //         title.textContent = "Top Performers";
    //         section.appendChild(title);

    //         const grid = document.createElement("div");
    //         grid.className = "grid grid-cols-1 md:grid-cols-2 gap-4";

    //         // Top Tools
    //         if (topData.tools && Array.isArray(topData.tools)) {
    //             const toolsCard = Admin.createTopItemCard("Tools", topData.tools);
    //             grid.appendChild(toolsCard);
    //         };

    //         // Top Resources
    //         if (topData.resources && Array.isArray(topData.resources)) {
    //             const resourcesCard = Admin.createTopItemCard(
    //                 "Resources",
    //                 topData.resources,
    //             );
    //             grid.appendChild(resourcesCard);
    //         };

    //         // Top Prompts
    //         if (topData.prompts && Array.isArray(topData.prompts)) {
    //             const promptsCard = Admin.createTopItemCard("Prompts", topData.prompts);
    //             grid.appendChild(promptsCard);
    //         };

    //         // Top Servers
    //         if (topData.servers && Array.isArray(topData.servers)) {
    //             const serversCard = Admin.createTopItemCard("Servers", topData.servers);
    //             grid.appendChild(serversCard);
    //         };

    //         section.appendChild(grid);
    //         return section;
    //     } catch (error) {
    //         console.error("Error creating top performers section:", error);
    //         return document.createElement("div"); // Safe fallback
    //     }
    // }
    // Removed unused function createEnhancedTopPerformersSection - handled by HTMX
    /* Admin.createEnhancedTopPerformersSection = function (topData) {
        try {
            const section = document.createElement("div");
            section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

            const title = document.createElement("h3");
            title.className = "text-lg font-medium mb-4 dark:text-gray-200";
            title.textContent = "Top Performers";
            title.setAttribute("aria-label", "Top Performers Section");
            section.appendChild(title);

            // Loading skeleton
            const skeleton = document.createElement("div");
            skeleton.className = "animate-pulse space-y-4";
            skeleton.innerHTML = `
                <div class="h-4 bg-gray-200 rounded w-1/4 dark:bg-gray-700"></div>
                <div class="space-y-2">
                    <div class="h-10 bg-gray-200 rounded dark:bg-gray-700"></div>
                    <div class="h-32 bg-gray-200 rounded dark:bg-gray-700"></div>
                </div>`;
            section.appendChild(skeleton);

            // Tabs
            const tabsContainer = document.createElement("div");
            tabsContainer.className =
                "border-b border-gray-200 dark:border-gray-700";
            const tabList = document.createElement("nav");
            tabList.className = "-mb-px flex space-x-8 overflow-x-auto";
            tabList.setAttribute("aria-label", "Top Performers Tabs");

            const entityTypes = [
                "tools",
                "resources",
                "prompts",
                "gateways",
                "servers",
            ];
            entityTypes.forEach((type, index) => {
                if (topData[type] && Array.isArray(topData[type])) {
                    const tab = Admin.createTab(type, index === 0);
                    tabList.appendChild(tab);
                }
            });

            tabsContainer.appendChild(tabList);
            section.appendChild(tabsContainer);

            // Content panels
            const contentContainer = document.createElement("div");
            contentContainer.className = "mt-4";

            entityTypes.forEach((type, index) => {
                if (topData[type] && Array.isArray(topData[type])) {
                    const panel = Admin.createTopPerformersTable(
                        type,
                        topData[type],
                        index === 0,
                    );
                    contentContainer.appendChild(panel);
                }
            });

            section.appendChild(contentContainer);

            // Remove skeleton once data is loaded
            setTimeout(() => skeleton.remove(), 500); // Simulate async data load

            // Export button
            const exportButton = document.createElement("button");
            exportButton.className =
                "mt-4 bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-600";
            exportButton.textContent = "Export Metrics";
            exportButton.onclick = () => Admin.exportMetricsToCSV(topData);
            section.appendChild(exportButton);

            return section;
        } catch (error) {
            console.error("Error creating enhanced top performers section:", error);
            Admin.showErrorMessage("Failed to load top performers section");
            return document.createElement("div");
        }
    } */
    Admin.calculateSuccessRate = function (item) {
        // API returns successRate directly as a percentage
        if (item.successRate !== undefined && item.successRate !== null) {
            return Math.round(item.successRate);
        }
        // Fallback for legacy format (if needed)
        const total =
            item.execution_count || item.executions || item.executionCount || 0;
        const successful = item.successful_count || item.successfulExecutions || 0;
        return total > 0 ? Math.round((successful / total) * 100) : 0;
    };

    Admin.formatNumber = function (num) {
        return new Intl.NumberFormat().format(num);
    };

    Admin.formatLastUsed = function (timestamp) {
        if (!timestamp) {
            return "Never";
        }

        let date;
        if (typeof timestamp === "number" || /^\d+$/.test(timestamp)) {
            const num = Admin.Number(timestamp);
            date = new Date(num < 1e12 ? num * 1000 : num); // epoch seconds or ms
        } else {
            date = new Date(timestamp.endsWith("Z") ? timestamp : timestamp + "Z");
        }

        if (Admin.isNaN(date.getTime())) {
            return "Never";
        }

        const now = Date.now();
        const diff = now - date.getTime();

        if (diff < 60 * 1000) {
            return "Just now";
        }
        if (diff < 60 * 60 * 1000) {
            return `${Math.floor(diff / 60000)} min ago`;
        }

        return date.toLocaleString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: true,
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        });
    };

    /* Unused - part of commented createEnhancedTopPerformersSection
    Admin.createTopPerformersTable = function (entityType, data, isActive) {
        const panel = document.createElement("div");
        panel.id = `top-${entityType}-panel`;
        panel.className = `transition-opacity duration-300 ${isActive ? "opacity-100" : "hidden opacity-0"}`;
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", `top-${entityType}-tab`);

        if (data.length === 0) {
            const emptyState = document.createElement("p");
            emptyState.className =
                "text-gray-500 dark:text-gray-400 text-center py-4";
            emptyState.textContent = `No ${entityType} data available`;
            panel.appendChild(emptyState);
            return panel;
        }

        // Responsive table wrapper
        const tableWrapper = document.createElement("div");
        tableWrapper.className = "overflow-x-auto sm:overflow-x-visible";

        const table = document.createElement("table");
        table.className =
            "min-w-full divide-y divide-gray-200 dark:divide-gray-700";

        // Table header
        const thead = document.createElement("thead");
        thead.className =
            "bg-gray-50 dark:bg-gray-700 hidden sm:table-header-group";
        const headerRow = document.createElement("tr");
        const headers = [
            "Rank",
            "Name",
            "Executions",
            "Avg Response Time",
            "Success Rate",
            "Last Used",
        ];

        headers.forEach((headerText, index) => {
            const th = document.createElement("th");
            th.className =
                "px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider";
            th.setAttribute("scope", "col");
            th.textContent = headerText;
            if (index === 0) {
                th.setAttribute("aria-sort", "ascending");
            }
            headerRow.appendChild(th);
        });

        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Table body
        const tbody = document.createElement("tbody");
        tbody.className =
            "bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700";

        // Pagination (if > 5 items)
        const paginatedData = data.slice(0, 5); // Limit to top 5
        paginatedData.forEach((item, index) => {
            const row = document.createElement("tr");
            row.className =
                "hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-200";

            // Rank
            const rankCell = document.createElement("td");
            rankCell.className =
                "px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100 sm:px-6 sm:py-4";
            const rankBadge = document.createElement("span");
            rankBadge.className = `inline-flex items-center justify-center w-6 h-6 rounded-full ${
                index === 0
                    ? "bg-yellow-400 text-yellow-900"
                    : index === 1
                    ? "bg-gray-300 text-gray-900"
                    : index === 2
                        ? "bg-orange-400 text-orange-900"
                        : "bg-gray-100 text-gray-600"
            }`;
            rankBadge.textContent = index + 1;
            rankBadge.setAttribute("aria-label", `Rank ${index + 1}`);
            rankCell.appendChild(rankBadge);
            row.appendChild(rankCell);

            // Name (clickable for drill-down)
            const nameCell = document.createElement("td");
            nameCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer";
            nameCell.textContent = Admin.escapeHtml(item.name || "Unknown");
            // nameCell.onclick = () => Admin.showDetailedMetrics(entityType, item.id);
            nameCell.setAttribute("role", "button");
            nameCell.setAttribute(
                "aria-label",
                `View details for ${item.name || "Unknown"}`,
            );
            row.appendChild(nameCell);

            // Executions
            const execCell = document.createElement("td");
            execCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            execCell.textContent = Admin.formatNumber(
                item.executionCount || item.execution_count || item.executions || 0,
            );
            row.appendChild(execCell);

            // Avg Response Time
            const avgTimeCell = document.createElement("td");
            avgTimeCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            const avgTime = item.avg_response_time || item.avgResponseTime;
            avgTimeCell.textContent = avgTime ? `${Math.round(avgTime)}ms` : "N/A";
            row.appendChild(avgTimeCell);

            // Success Rate
            const successCell = document.createElement("td");
            successCell.className =
                "px-6 py-4 whitespace-nowrap text-sm sm:px-6 sm:py-4";
            const successRate = Admin.calculateSuccessRate(item);
            const successBadge = document.createElement("span");
            successBadge.className = `inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                successRate >= 95
                    ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
                    : successRate >= 80
                    ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-100"
                    : "bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100"
            }`;
            successBadge.textContent = `${successRate}%`;
            successBadge.setAttribute(
                "aria-label",
                `Success rate: ${successRate}%`,
            );
            successCell.appendChild(successBadge);
            row.appendChild(successCell);

            // Last Used
            const lastUsedCell = document.createElement("td");
            lastUsedCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            lastUsedCell.textContent = Admin.formatLastUsed(
                item.last_execution || item.lastExecution,
            );
            row.appendChild(lastUsedCell);

            tbody.appendChild(row);
        });

        table.appendChild(tbody);
        tableWrapper.appendChild(table);
        panel.appendChild(tableWrapper);

        // Pagination controls (using standard Alpine.js pattern)
        if (data.length > 5) {
            const pagination = Admin.createStandardPaginationControls(
                `top-${entityType}`,
                data.length,
                5,
                (page, perPage) => {
                    Admin.updateTableRows(tbody, entityType, data, page, perPage);
                },
                },
            );
            panel.appendChild(pagination);
        }

        return panel;
    }
    */

    /* Unused - part of commented createEnhancedTopPerformersSection
    Admin.createTab = function (type, isActive) {
        const tab = document.createElement("a");
        tab.href = "#";
        tab.id = `top-${type}-tab`;
        tab.className = `${
            isActive
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300"
        } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm capitalize transition-colors duration-200 sm:py-4 sm:px-1`;
        tab.textContent = type;
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", `top-${type}-panel`);
        tab.setAttribute("aria-selected", isActive.toString());
        tab.onclick = (e) => {
            e.preventDefault();
            Admin.showTopPerformerTab(type);
        };
        return tab;
    }
    */

    // eslint-disable-next-line no-unused-vars
    Admin.showTopPerformerTab = function (activeType) {
        const entityTypes = [
            "tools",
            "resources",
            "prompts",
            "gateways",
            "servers",
        ];
        entityTypes.forEach((type) => {
            const panel = Admin.safeGetElement(`top-${type}-panel`);
            const tab = Admin.safeGetElement(`top-${type}-tab`);
            if (panel) {
                panel.classList.toggle("hidden", type !== activeType);
                panel.classList.toggle("opacity-100", type === activeType);
                panel.classList.toggle("opacity-0", type !== activeType);
                panel.setAttribute("aria-hidden", type !== activeType);
            }
            if (tab) {
                tab.classList.toggle("border-indigo-500", type === activeType);
                tab.classList.toggle("text-indigo-600", type === activeType);
                tab.classList.toggle("dark:text-indigo-400", type === activeType);
                tab.classList.toggle("border-transparent", type !== activeType);
                tab.classList.toggle("text-gray-500", type !== activeType);
                tab.setAttribute("aria-selected", type === activeType);
            }
        });
    };

    /**
    * Creates standard Alpine.js-based pagination controls matching the pattern
    * used in Tools/Resources/Prompts sections for visual consistency
    */
    // eslint-disable-next-line no-unused-vars
    Admin.createStandardPaginationControls = function (
        idPrefix,
        totalItems,
        initialPerPage,
        onPageChange,
    ) {
        const wrapper = document.createElement("div");

        // Store callback in a global namespace for Alpine.js to access
        const callbackId = `pagination_${idPrefix}_${Date.now()}`;
        window[callbackId] = onPageChange;

        wrapper.setAttribute(
            "x-data",
            `{
            currentPage: 1,
            perPage: ${initialPerPage},
            totalItems: ${totalItems},
            callbackId: '${callbackId}',
            get totalPages() { return Math.ceil(this.totalItems / this.perPage); },
            get hasNext() { return this.currentPage < this.totalPages; },
            get hasPrev() { return this.currentPage > 1; },
            get startItem() { return Math.min((this.currentPage - 1) * this.perPage + 1, this.totalItems); },
            get endItem() { return Math.min(this.currentPage * this.perPage, this.totalItems); },

            goToPage(page) {
                if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
                    this.currentPage = page;
                    window[this.callbackId](this.currentPage, this.perPage);
                }
            },
            prevPage() {
                if (this.hasPrev) { this.goToPage(this.currentPage - 1); }
            },
            nextPage() {
                if (this.hasNext) { this.goToPage(this.currentPage + 1); }
            },
            changePageSize(size) {
                this.perPage = parseInt(size);
                this.currentPage = 1;
                window[this.callbackId](this.currentPage, this.perPage);
            }
        }`,
        );
        wrapper.className =
            "flex flex-col sm:flex-row items-center justify-between gap-4 py-4 border-t border-gray-200 dark:border-gray-700";

        wrapper.innerHTML = `
            <!-- Page Size Selector -->
            <div class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <span>Show:</span>
                <select
                    x-model="perPage"
                    @change="changePageSize($event.target.value)"
                    class="px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-400"
                >
                    <option value="5">5</option>
                    <option value="10">10</option>
                    <option value="25">25</option>
                    <option value="50">50</option>
                    <option value="100">100</option>
                </select>
                <span>per page</span>
            </div>

            <!-- Page Info -->
            <div class="text-sm text-gray-700 dark:text-gray-300">
                <span x-text="\`Showing \${startItem} - \${endItem} of \${totalItems.toLocaleString()} items\`"></span>
            </div>

            <!-- Page Navigation -->
            <div class="flex items-center gap-2">
                <!-- First Page Button -->
                <button
                    @click="goToPage(1)"
                    :disabled="!hasPrev"
                    :class="hasPrev ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                    class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                    title="First Page"
                >
                    ⏮️
                </button>

                <!-- Previous Page Button -->
                <button
                    @click="prevPage()"
                    :disabled="!hasPrev"
                    :class="hasPrev ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                    class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                    title="Previous Page"
                >
                    ◀️ Prev
                </button>

                <!-- Page Number Display -->
                <div class="flex items-center gap-1">
                    <!-- Show first page if not near start -->
                    <template x-if="currentPage > 3">
                        <button
                            @click="goToPage(1)"
                            class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                        >
                            1
                        </button>
                    </template>

                    <!-- Ellipsis if needed -->
                    <template x-if="currentPage > 4">
                        <span class="px-2 text-gray-500 dark:text-gray-500">...</span>
                    </template>

                    <!-- Show 2 pages before current -->
                    <template x-for="i in [currentPage - 2, currentPage - 1]" :key="i">
                        <button
                            x-show="i >= 1"
                            @click="goToPage(i)"
                            class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                            x-text="i"
                        ></button>
                    </template>

                    <!-- Current Page (highlighted) -->
                    <button
                        class="px-3 py-1 rounded-md border-2 border-indigo-600 dark:border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 font-semibold text-indigo-700 dark:text-indigo-300"
                        disabled
                        x-text="currentPage"
                    ></button>

                    <!-- Show 2 pages after current -->
                    <template x-for="i in [currentPage + 1, currentPage + 2]" :key="i">
                        <button
                            x-show="i <= totalPages"
                            @click="goToPage(i)"
                            class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                            x-text="i"
                        ></button>
                    </template>

                    <!-- Ellipsis if needed -->
                    <template x-if="currentPage < totalPages - 3">
                        <span class="px-2 text-gray-500 dark:text-gray-500">...</span>
                    </template>

                    <!-- Show last page if not near end -->
                    <template x-if="currentPage < totalPages - 2">
                        <button
                            @click="goToPage(totalPages)"
                            class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-gray-700 dark:text-gray-300"
                            x-text="totalPages"
                        ></button>
                    </template>
                </div>

                <!-- Next Page Button -->
                <button
                    @click="nextPage()"
                    :disabled="!hasNext"
                    :class="hasNext ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                    class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                    title="Next Page"
                >
                    Next ▶️
                </button>

                <!-- Last Page Button -->
                <button
                    @click="goToPage(totalPages)"
                    :disabled="!hasNext"
                    :class="hasNext ? 'text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20' : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'"
                    class="px-3 py-1 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 transition-colors"
                    title="Last Page"
                >
                    ⏭️
                </button>
            </div>
        `;
        return wrapper;
    };

    // eslint-disable-next-line no-unused-vars
    Admin.updateTableRows = function (tbody, entityType, data, page, perPage) {
        tbody.innerHTML = "";
        const start = (page - 1) * perPage;
        const paginatedData = data.slice(start, start + perPage);

        paginatedData.forEach((item, localIndex) => {
            const globalIndex = start + localIndex; // Calculate global rank
            const row = document.createElement("tr");
            row.className =
                "hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-200";

            // Rank
            const rankCell = document.createElement("td");
            rankCell.className =
                "px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100 sm:px-6 sm:py-4";
            const rankBadge = document.createElement("span");
            rankBadge.className = `inline-flex items-center justify-center w-6 h-6 rounded-full ${
                globalIndex === 0
                    ? "bg-yellow-400 text-yellow-900"
                    : globalIndex === 1
                    ? "bg-gray-300 text-gray-900"
                    : globalIndex === 2
                        ? "bg-orange-400 text-orange-900"
                        : "bg-gray-100 text-gray-600"
            }`;
            rankBadge.textContent = globalIndex + 1;
            rankBadge.setAttribute("aria-label", `Rank ${globalIndex + 1}`);
            rankCell.appendChild(rankBadge);
            row.appendChild(rankCell);

            // Name (clickable for drill-down)
            const nameCell = document.createElement("td");
            nameCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-indigo-600 dark:text-indigo-400 cursor-pointer";
            nameCell.textContent = Admin.escapeHtml(item.name || "Unknown");
            nameCell.setAttribute("role", "button");
            nameCell.setAttribute(
                "aria-label",
                `View details for ${item.name || "Unknown"}`,
            );
            row.appendChild(nameCell);

            // Executions
            const execCell = document.createElement("td");
            execCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            execCell.textContent = Admin.formatNumber(
                item.executionCount || item.execution_count || item.executions || 0,
            );
            row.appendChild(execCell);

            // Avg Response Time
            const avgTimeCell = document.createElement("td");
            avgTimeCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            const avgTime = item.avg_response_time || item.avgResponseTime;
            avgTimeCell.textContent = avgTime ? `${Math.round(avgTime)}ms` : "N/A";
            row.appendChild(avgTimeCell);

            // Success Rate
            const successCell = document.createElement("td");
            successCell.className =
                "px-6 py-4 whitespace-nowrap text-sm sm:px-6 sm:py-4";
            const successRate = Admin.calculateSuccessRate(item);
            const successBadge = document.createElement("span");
            successBadge.className = `inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                successRate >= 95
                    ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
                    : successRate >= 80
                    ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-100"
                    : "bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100"
            }`;
            successBadge.textContent = `${successRate}%`;
            successBadge.setAttribute(
                "aria-label",
                `Success rate: ${successRate}%`,
            );
            successCell.appendChild(successBadge);
            row.appendChild(successCell);

            // Last Used
            const lastUsedCell = document.createElement("td");
            lastUsedCell.className =
                "px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 sm:px-6 sm:py-4";
            lastUsedCell.textContent = Admin.formatLastUsed(
                item.last_execution || item.lastExecution,
            );
            row.appendChild(lastUsedCell);

            tbody.appendChild(row);
        });
    };

    /* Unused - part of commented createEnhancedTopPerformersSection
    Admin.exportMetricsToCSV = function (topData) {
        const headers = [
            "Entity Type",
            "Rank",
            "Name",
            "Executions",
            "Avg Response Time",
            "Success Rate",
            "Last Used",
        ];
        const rows = [];

        ["tools", "resources", "prompts", "gateways", "servers"].forEach((type) => {
            if (topData[type] && Array.isArray(topData[type])) {
                topData[type].forEach((item, index) => {
                    rows.push([
                        type,
                        index + 1,
                        `"${escapeHtml(item.name || "Unknown")}"`,
                        Admin.formatNumber(
                            item.executionCount ||
                                item.execution_count ||
                                item.executions ||
                                0,
                        ),
                        item.avg_response_time || item.avgResponseTime
                            ? `${Math.round(item.avg_response_time || item.avgResponseTime)}ms`
                            : "N/A",
                        `${calculateSuccessRate(item)}%`,
                        Admin.formatLastUsed(item.last_execution || item.lastExecution),
                    ]);
                });
            }
        });

        const csv = [headers.join(","), ...rows.map((row) => row.join(","))].join(
            "\n",
        );
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `top_performers_${new Date().toISOString()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }
    */

    /**
    * SECURITY: Create top item card with safe content handling
    */
    // Admin.createTopItemCard = function (title, items) {
    //     try {
    //         const card = document.createElement("div");
    //         card.className = "bg-gray-50 rounded p-4 dark:bg-gray-700";

    //         const cardTitle = document.createElement("h4");
    //         cardTitle.className = "font-medium mb-2 dark:text-gray-200";
    //         cardTitle.textContent = `Top ${title}`;
    //         card.appendChild(cardTitle);

    //         const list = document.createElement("ul");
    //         list.className = "space-y-1";

    //         items.slice(0, 5).forEach((item) => {
    //             const listItem = document.createElement("li");
    //             listItem.className =
    //                 "text-sm text-gray-600 dark:text-gray-300 flex justify-between";

    //             const nameSpan = document.createElement("span");
    //             nameSpan.textContent = item.name || "Unknown";

    //             const countSpan = document.createElement("span");
    //             countSpan.className = "font-medium";
    //             countSpan.textContent = String(item.executions || 0);

    //             listItem.appendChild(nameSpan);
    //             listItem.appendChild(countSpan);
    //             list.appendChild(listItem);
    //         });

    //         card.appendChild(list);
    //         return card;
    //     } catch (error) {
    //         console.error("Error creating top item card:", error);
    //         return document.createElement("div"); // Safe fallback
    //     }
    // };

    /**
    * SECURITY: Create performance metrics card with safe display
    */
    Admin.createPerformanceCard = function (performanceData) {
        try {
            const card = document.createElement("div");
            card.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

            const titleElement = document.createElement("h3");
            titleElement.className = "text-lg font-medium mb-4 dark:text-gray-200";
            titleElement.textContent = "Performance Metrics";
            card.appendChild(titleElement);

            const metricsList = document.createElement("div");
            metricsList.className = "space-y-2";

            // Define performance metrics with safe structure
            const performanceMetrics = [
                { key: "memoryUsage", label: "Memory Usage" },
                { key: "cpuUsage", label: "CPU Usage" },
                { key: "diskIo", label: "Disk I/O" },
                { key: "networkThroughput", label: "Network Throughput" },
                { key: "cacheHitRate", label: "Cache Hit Rate" },
                { key: "activeThreads", label: "Active Threads" },
            ];

            performanceMetrics.forEach((metric) => {
                const value =
                    performanceData[metric.key] ??
                    performanceData[
                        metric.key.replace(/([A-Z])/g, "_$1").toLowerCase()
                    ] ??
                    "N/A";

                const metricRow = document.createElement("div");
                metricRow.className = "flex justify-between";

                const label = document.createElement("span");
                label.className = "text-gray-600 dark:text-gray-400";
                label.textContent = metric.label + ":";

                const valueSpan = document.createElement("span");
                valueSpan.className = "font-medium dark:text-gray-200";
                valueSpan.textContent = value === "N/A" ? "N/A" : String(value);

                metricRow.appendChild(label);
                metricRow.appendChild(valueSpan);
                metricsList.appendChild(metricRow);
            });

            card.appendChild(metricsList);
            return card;
        } catch (error) {
            console.error("Error creating performance card:", error);
            return document.createElement("div"); // Safe fallback
        }
    };

    /**
    * SECURITY: Create recent activity section with safe content handling
    */
    Admin.createRecentActivitySection = function (activityData) {
        try {
            const section = document.createElement("div");
            section.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

            const title = document.createElement("h3");
            title.className = "text-lg font-medium mb-4 dark:text-gray-200";
            title.textContent = "Recent Activity";
            section.appendChild(title);

            if (Array.isArray(activityData) && activityData.length > 0) {
                const activityList = document.createElement("div");
                activityList.className = "space-y-3 max-h-64 overflow-y-auto";

                // Display up to 10 recent activities safely
                activityData.slice(0, 10).forEach((activity) => {
                    const activityItem = document.createElement("div");
                    activityItem.className =
                        "flex items-center justify-between p-2 bg-gray-50 rounded dark:bg-gray-700";

                    const leftSide = document.createElement("div");

                    const actionSpan = document.createElement("span");
                    actionSpan.className = "font-medium dark:text-gray-200";
                    actionSpan.textContent = Admin.escapeHtml(
                        activity.action || "Unknown Action",
                    );

                    const targetSpan = document.createElement("span");
                    targetSpan.className =
                        "text-sm text-gray-500 dark:text-gray-400 ml-2";
                    targetSpan.textContent = Admin.escapeHtml(activity.target || "");

                    leftSide.appendChild(actionSpan);
                    leftSide.appendChild(targetSpan);

                    const rightSide = document.createElement("div");
                    rightSide.className = "text-xs text-gray-400";
                    rightSide.textContent = Admin.escapeHtml(activity.timestamp || "");

                    activityItem.appendChild(leftSide);
                    activityItem.appendChild(rightSide);
                    activityList.appendChild(activityItem);
                });

                section.appendChild(activityList);
            } else {
                const noActivity = document.createElement("p");
                noActivity.className =
                    "text-gray-500 dark:text-gray-400 text-center py-4";
                noActivity.textContent = "No recent activity to display";
                section.appendChild(noActivity);
            }

            return section;
        } catch (error) {
            console.error("Error creating recent activity section:", error);
            return document.createElement("div"); // Safe fallback
        }
    };

    Admin.createMetricsCard = function (title, metrics) {
        const card = document.createElement("div");
        card.className = "bg-white rounded-lg shadow p-6 dark:bg-gray-800";

        const titleElement = document.createElement("h3");
        titleElement.className = "text-lg font-medium mb-4 dark:text-gray-200";
        titleElement.textContent = `${title} Metrics`;
        card.appendChild(titleElement);

        const metricsList = document.createElement("div");
        metricsList.className = "space-y-2";

        const metricsToShow = [
            { key: "totalExecutions", label: "Total Executions" },
            { key: "successfulExecutions", label: "Successful Executions" },
            { key: "failedExecutions", label: "Failed Executions" },
            { key: "failureRate", label: "Failure Rate" },
            { key: "avgResponseTime", label: "Average Response Time" },
            { key: "lastExecutionTime", label: "Last Execution Time" },
        ];

        metricsToShow.forEach((metric) => {
            const value =
                metrics[metric.key] ??
                metrics[metric.key.replace(/([A-Z])/g, "_$1").toLowerCase()] ??
                "N/A";

            const metricRow = document.createElement("div");
            metricRow.className = "flex justify-between";

            const label = document.createElement("span");
            label.className = "text-gray-600 dark:text-gray-400";
            label.textContent = metric.label + ":";

            const valueSpan = document.createElement("span");
            valueSpan.className = "font-medium dark:text-gray-200";
            valueSpan.textContent = value === "N/A" ? "N/A" : String(value);

            metricRow.appendChild(label);
            metricRow.appendChild(valueSpan);
            metricsList.appendChild(metricRow);
        });

        card.appendChild(metricsList);
        return card;
    };
})(window.Admin)