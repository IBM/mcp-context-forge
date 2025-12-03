/**
 * ====================================================================
 * POOL MANAGEMENT - Session Pooling UI for MCP Gateway
 * ====================================================================
 *
 * Provides UI functionality for:
 * - Pool configuration management
 * - Real-time pool statistics monitoring
 * - Strategy optimization
 * - Session management
 * - Health monitoring
 * - Pool control operations (drain, resize, reset)
 *
 * VERSION: 2.1.0 - Phase 6 Complete: Added pool control operations
 * - Added drainPool() function
 * - Added resizePool() function
 * - Added resetPool() function
 * - Enhanced pool stats modal with control buttons
 */

// ===================================================================
// POOL CONFIGURATION MANAGEMENT
// ===================================================================

/**
 * Open pool configuration modal for a server
 * @param {string} serverId - The server ID
 */
async function openPoolConfig(serverId) {
    console.log(`Opening pool config for server: ${serverId}`);
    
    // Fetch current pool configuration
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/config`
    );
    
    if (!response.ok) {
        console.error('Failed to load pool config:', response.statusText);
        showPoolNotification('Failed to load pool configuration', 'error');
        return;
    }
    
    try {
        const config = await response.json();
        // Show modal with configuration
        showPoolConfigModal(serverId, config);
    } catch (error) {
        console.error('Error parsing pool config response:', error);
        showPoolNotification('Failed to parse pool configuration', 'error');
    }
}

/**
 * Display pool configuration modal
 * @param {string} serverId - The server ID
 * @param {Object} config - Current pool configuration
 */
function showPoolConfigModal(serverId, config) {
    const modal = document.createElement('div');
    modal.id = 'pool-config-modal';
    modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
    
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="flex justify-between items-center pb-3 border-b dark:border-gray-700">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    🔄 Pool Configuration
                </h3>
                <button onclick="closePoolConfigModal()" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            
            <form id="pool-config-form" class="mt-4 space-y-4">
                <!-- Enable Pooling -->
                <div class="flex items-center justify-between">
                    <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                        Enable Session Pooling
                    </label>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="pool-enabled" ${config.enabled ? 'checked' : ''} 
                               class="sr-only peer" onchange="togglePoolFields(this.checked)">
                        <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
                    </label>
                </div>
                
                <div id="pool-fields" ${config.enabled ? '' : 'style="display:none"'}>
                    <!-- Pool Strategy -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                            Pool Strategy
                        </label>
                        <select id="pool-strategy" class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                            <option value="round_robin" ${config.strategy === 'round_robin' ? 'selected' : ''}>Round Robin</option>
                            <option value="least_connections" ${config.strategy === 'least_connections' ? 'selected' : ''}>Least Connections</option>
                            <option value="sticky" ${config.strategy === 'sticky' ? 'selected' : ''}>Sticky Sessions</option>
                            <option value="weighted" ${config.strategy === 'weighted' ? 'selected' : ''}>Weighted</option>
                            <option value="none" ${config.strategy === 'none' ? 'selected' : ''}>None (Direct)</option>
                        </select>
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            Strategy for selecting sessions from the pool
                        </p>
                    </div>
                    
                    <!-- Pool Size Configuration -->
                    <div class="grid grid-cols-3 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                Min Size
                            </label>
                            <input type="number" id="pool-min-size" value="${config.min_size || 1}" min="1" max="100"
                                   class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                Max Size
                            </label>
                            <input type="number" id="pool-max-size" value="${config.max_size || 10}" min="1" max="100"
                                   class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                Pool Size
                            </label>
                            <input type="number" id="pool-target-size" value="${config.size || 5}" min="1" max="100"
                                   class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                        </div>
                    </div>
                    
                    <!-- Timeouts -->
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                Acquisition Timeout (seconds)
                            </label>
                            <input type="number" id="pool-idle-timeout" value="${config.timeout || 30}" min="1" max="300"
                                   class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                Timeout for acquiring a session from the pool
                            </p>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                                Max Idle Time (seconds)
                            </label>
                            <input type="number" id="pool-max-lifetime" value="${config.max_idle_time || 3600}" min="60" max="86400"
                                   class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-gray-300">
                            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                                Maximum time a session can remain idle before recycling
                            </p>
                        </div>
                    </div>
                    
                    <!-- Auto-scaling -->
                    <div class="flex items-center justify-between">
                        <div>
                            <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Enable Auto-scaling
                            </label>
                            <p class="text-xs text-gray-500 dark:text-gray-400">
                                Automatically adjust pool size based on demand
                            </p>
                        </div>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" id="pool-auto-scale" ${config.auto_scale ? 'checked' : ''}
                                   class="sr-only peer">
                            <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
                        </label>
                    </div>
                </div>
                
                <!-- Action Buttons -->
                <div class="flex justify-end space-x-3 pt-4 border-t dark:border-gray-700">
                    <button type="button" onclick="closePoolConfigModal()" 
                            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md">
                        Cancel
                    </button>
                    <button type="submit" 
                            class="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md">
                        Save Configuration
                    </button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Attach form submit handler
    document.getElementById('pool-config-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await savePoolConfig(serverId);
    });
}

/**
 * Toggle pool configuration fields visibility
 * @param {boolean} enabled - Whether pooling is enabled
 */
function togglePoolFields(enabled) {
    const fields = document.getElementById('pool-fields');
    if (fields) {
        fields.style.display = enabled ? 'block' : 'none';
    }
}

/**
 * Close pool configuration modal
 */
function closePoolConfigModal() {
    const modal = document.getElementById('pool-config-modal');
    if (modal) {
        modal.remove();
    }
}

/**
 * Save pool configuration
 * @param {string} serverId - The server ID
 */
async function savePoolConfig(serverId) {
    const enabled = document.getElementById('pool-enabled').checked;
    
    const config = {
        enabled: enabled,
        strategy: enabled ? document.getElementById('pool-strategy').value : 'none',
        min_size: enabled ? parseInt(document.getElementById('pool-min-size').value) : 0,
        max_size: enabled ? parseInt(document.getElementById('pool-max-size').value) : 0,
        size: enabled ? parseInt(document.getElementById('pool-target-size').value) : 0,
        timeout: enabled ? parseInt(document.getElementById('pool-idle-timeout').value) : 300,
        max_idle_time: enabled ? parseInt(document.getElementById('pool-max-lifetime').value) : 3600,
        auto_scale: enabled ? document.getElementById('pool-auto-scale').checked : false,
        health_check_interval: 60,  // Default value
        rebalance_interval: 300  // Default value
    };
    
    // Validate configuration
    if (enabled) {
        if (config.min_size > config.max_size) {
            showPoolNotification('Min size cannot be greater than max size', 'error');
            return;
        }
        if (config.size < config.min_size || config.size > config.max_size) {
            showPoolNotification('Pool size must be between min and max size', 'error');
            return;
        }
    }
    
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/config`,
        {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(config)
        }
    );
    
    if (!response.ok) {
        console.error('Failed to save pool config:', response.statusText);
        showPoolNotification('Failed to save pool configuration', 'error');
        return;
    }
    
    showPoolNotification('Pool configuration saved successfully', 'success');
    closePoolConfigModal();
    
    // Refresh pool stats if visible
    if (window.currentPoolStatsServerId === serverId) {
        await refreshPoolStats(serverId);
    }
}

// ===================================================================
// POOL STATISTICS & MONITORING
// ===================================================================

/**
 * Show pool statistics for a server
 * @param {string} serverId - The server ID
 */
async function showPoolStats(serverId) {
    console.log(`Loading pool stats for server: ${serverId}`);
    window.currentPoolStatsServerId = serverId;
    
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/stats`
    );
    
    if (!response.ok) {
        console.error('Failed to load pool stats:', response.statusText);
        showPoolNotification('Failed to load pool statistics', 'error');
        return;
    }
    
    try {
        const stats = await response.json();
        // Show modal with statistics
        showPoolStatsModal(serverId, stats);
        // Start auto-refresh
        startPoolStatsAutoRefresh(serverId);
    } catch (error) {
        console.error('Error parsing pool stats:', error);
        showPoolNotification('Failed to parse pool statistics', 'error');
    }
}

/**
 * Display pool statistics modal
 * @param {string} serverId - The server ID
 * @param {Object} stats - Pool statistics
 */
function showPoolStatsModal(serverId, stats) {
    // Remove existing modal if present
    const existingModal = document.getElementById('pool-stats-modal');
    if (existingModal) {
        existingModal.remove();
    }
    
    const modal = document.createElement('div');
    modal.id = 'pool-stats-modal';
    modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
    
    const healthColor = stats.health_status === 'healthy' ? 'green' : 
                       stats.health_status === 'degraded' ? 'yellow' : 'red';
    
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-4xl shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="flex justify-between items-center pb-3 border-b dark:border-gray-700">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    📊 Pool Statistics
                </h3>
                <button onclick="closePoolStatsModal()" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            
            <div id="pool-stats-content" class="mt-4 space-y-4">
                <!-- Health Status -->
                <div class="flex items-center justify-between p-4 bg-${healthColor}-50 dark:bg-${healthColor}-900/20 rounded-lg">
                    <div>
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Health Status</p>
                        <p class="text-2xl font-bold text-${healthColor}-600 dark:text-${healthColor}-400 capitalize">
                            ${stats.health_status}
                        </p>
                    </div>
                    <div class="text-right">
                        <p class="text-sm text-gray-600 dark:text-gray-400">Success Rate</p>
                        <p class="text-xl font-semibold text-gray-900 dark:text-gray-100">
                            ${(stats.success_rate * 100).toFixed(1)}%
                        </p>
                    </div>
                </div>
                
                <!-- Session Counts -->
                <div class="grid grid-cols-3 gap-4">
                    <div class="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Total Sessions</p>
                        <p class="text-2xl font-bold text-blue-600 dark:text-blue-400">${stats.total_sessions}</p>
                    </div>
                    <div class="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Active Sessions</p>
                        <p class="text-2xl font-bold text-green-600 dark:text-green-400">${stats.active_sessions}</p>
                    </div>
                    <div class="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Available Sessions</p>
                        <p class="text-2xl font-bold text-purple-600 dark:text-purple-400">${stats.available_sessions}</p>
                    </div>
                </div>
                
                <!-- Performance Metrics -->
                <div class="grid grid-cols-2 gap-4">
                    <div class="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Avg Response Time</p>
                        <p class="text-xl font-semibold text-gray-900 dark:text-gray-100">
                            ${stats.avg_response_time_ms ? stats.avg_response_time_ms.toFixed(2) + ' ms' : 'N/A'}
                        </p>
                    </div>
                    <div class="p-4 bg-gray-50 dark:bg-gray-700 rounded-lg">
                        <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Current Strategy</p>
                        <p class="text-xl font-semibold text-gray-900 dark:text-gray-100 capitalize">
                            ${stats.strategy ? stats.strategy.replace('_', ' ') : 'N/A'}
                        </p>
                    </div>
                </div>
                
                <!-- Request Counts -->
                <div class="grid grid-cols-3 gap-4">
                    <div class="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                        <p class="text-xs font-medium text-gray-600 dark:text-gray-400">Total Requests</p>
                        <p class="text-lg font-semibold text-gray-900 dark:text-gray-100">${stats.total_requests}</p>
                    </div>
                    <div class="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                        <p class="text-xs font-medium text-gray-600 dark:text-gray-400">Successful</p>
                        <p class="text-lg font-semibold text-green-600 dark:text-green-400">${stats.successful_requests}</p>
                    </div>
                    <div class="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                        <p class="text-xs font-medium text-gray-600 dark:text-gray-400">Failed</p>
                        <p class="text-lg font-semibold text-red-600 dark:text-red-400">${stats.failed_requests}</p>
                    </div>
                </div>
                
                <!-- Action Buttons -->
                <div class="space-y-3 pt-4 border-t dark:border-gray-700">
                    <!-- Primary Actions -->
                    <div class="flex justify-between">
                        <div class="space-x-2">
                            <button onclick="optimizePoolStrategy('${serverId}')"
                                    class="px-4 py-2 text-sm font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-md transition-colors"
                                    title="Analyze and recommend optimal pool strategy">
                                🎯 Optimize Strategy
                            </button>
                            <button onclick="viewPoolSessions('${serverId}')"
                                    class="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
                                    title="View active sessions in this pool">
                                👁️ View Sessions
                            </button>
                        </div>
                        <button onclick="refreshPoolStats('${serverId}')"
                                class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md transition-colors"
                                title="Refresh pool statistics">
                            🔄 Refresh
                        </button>
                    </div>
                    
                    <!-- Pool Control Actions -->
                    <div class="flex space-x-2">
                        <button onclick="drainPool('${serverId}')"
                                class="flex-1 px-4 py-2 text-sm font-medium text-white bg-orange-600 hover:bg-orange-700 rounded-md transition-colors"
                                title="Prevent new acquisitions, allow existing sessions to complete">
                            🚰 Drain Pool
                        </button>
                        <button onclick="resizePool('${serverId}')"
                                class="flex-1 px-4 py-2 text-sm font-medium text-white bg-cyan-600 hover:bg-cyan-700 rounded-md transition-colors"
                                title="Dynamically change pool size">
                            📏 Resize Pool
                        </button>
                        <button onclick="resetPool('${serverId}')"
                                class="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors"
                                title="Close all sessions and recreate pool">
                            🔄 Reset Pool
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/**
 * Refresh pool statistics
 * @param {string} serverId - The server ID
 */
async function refreshPoolStats(serverId) {
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/stats`
    );
    
    if (!response.ok) {
        console.error('Error refreshing pool stats:', response.statusText);
        return;
    }
    
    try {
        const stats = await response.json();
        // Update the modal content
        const modal = document.getElementById('pool-stats-modal');
        if (modal) {
            showPoolStatsModal(serverId, stats);
        }
    } catch (error) {
        console.error('Error parsing refreshed pool stats:', error);
    }
}

/**
 * Start auto-refresh for pool statistics
 * @param {string} serverId - The server ID
 */
function startPoolStatsAutoRefresh(serverId) {
    // Clear any existing interval
    if (window.poolStatsRefreshInterval) {
        clearInterval(window.poolStatsRefreshInterval);
    }
    
    // Refresh every 5 seconds
    window.poolStatsRefreshInterval = setInterval(() => {
        const modal = document.getElementById('pool-stats-modal');
        if (modal && window.currentPoolStatsServerId === serverId) {
            refreshPoolStats(serverId);
        } else {
            clearInterval(window.poolStatsRefreshInterval);
        }
    }, 5000);
}

/**
 * Close pool statistics modal
 */
function closePoolStatsModal() {
    const modal = document.getElementById('pool-stats-modal');
    if (modal) {
        modal.remove();
    }
    
    // Clear auto-refresh
    if (window.poolStatsRefreshInterval) {
        clearInterval(window.poolStatsRefreshInterval);
        window.poolStatsRefreshInterval = null;
    }
    
    window.currentPoolStatsServerId = null;
}

// ===================================================================
// POOL OPTIMIZATION
// ===================================================================

/**
 * Optimize pool strategy
 * @param {string} serverId - The server ID
 */
async function optimizePoolStrategy(serverId) {
    console.log(`Optimizing pool strategy for server: ${serverId}`);
    
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/optimize`,
        {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        }
    );
    
    if (!response.ok) {
        console.error('Failed to optimize pool strategy:', response.statusText);
        showPoolNotification('Failed to optimize pool strategy', 'error');
        return;
    }
    
    try {
        const result = await response.json();
        showPoolNotification(
            `Strategy optimized: ${result.old_strategy} → ${result.new_strategy}`,
            'success'
        );
        // Refresh stats
        await refreshPoolStats(serverId);
    } catch (error) {
        console.error('Error parsing optimize result:', error);
    }
}

// ===================================================================
// SESSION MANAGEMENT
// ===================================================================

/**
 * View pool sessions
 * @param {string} serverId - The server ID
 */
async function viewPoolSessions(serverId) {
    console.log(`Loading pool sessions for server: ${serverId}`);
    
    const response = await fetchWithTimeout(
        `${window.ROOT_PATH}/servers/${serverId}/pool/sessions`
    );
    
    if (!response.ok) {
        console.error('Failed to load pool sessions:', response.statusText);
        showPoolNotification('Failed to load pool sessions', 'error');
        return;
    }
    
    try {
        const data = await response.json();
        console.log('Pool sessions data:', data);
        
        // Handle different response formats
        const sessions = data.sessions || data || [];
        
        // Show sessions modal
        showPoolSessionsModal(serverId, sessions);
    } catch (error) {
        console.error('Error parsing pool sessions:', error);
        showPoolNotification('Failed to parse pool sessions', 'error');
    }
}

/**
 * Display pool sessions modal
 * @param {string} serverId - The server ID
 * @param {Array} sessions - List of sessions
 */
function showPoolSessionsModal(serverId, sessions) {
    const modal = document.createElement('div');
    modal.id = 'pool-sessions-modal';
    modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
    
    const sessionsHtml = sessions.map(session => `
        <tr class="border-b dark:border-gray-700">
            <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-100">${session.session_id.substring(0, 8)}...</td>
            <td class="px-4 py-3 text-sm">
                <span class="px-2 py-1 rounded-full text-xs font-medium ${
                    session.state === 'active' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' :
                    session.state === 'available' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300' :
                    'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                }">
                    ${session.state}
                </span>
            </td>
            <td class="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">${session.request_count}</td>
            <td class="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">${new Date(session.created_at).toLocaleString()}</td>
            <td class="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">${new Date(session.last_used_at).toLocaleString()}</td>
        </tr>
    `).join('');
    
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-5xl shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="flex justify-between items-center pb-3 border-b dark:border-gray-700">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    👁️ Pool Sessions (${sessions.length})
                </h3>
                <button onclick="closePoolSessionsModal()" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            
            <div class="mt-4 overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead class="bg-gray-50 dark:bg-gray-700">
                        <tr>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Session ID</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">State</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Requests</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Created</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Last Used</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200 dark:bg-gray-800 dark:divide-gray-700">
                        ${sessionsHtml || '<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">No sessions found</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <div class="flex justify-end pt-4 border-t dark:border-gray-700 mt-4">
                <button onclick="closePoolSessionsModal()" 
                        class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md">
                    Close
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/**
 * Close pool sessions modal
 */
function closePoolSessionsModal() {
    const modal = document.getElementById('pool-sessions-modal');
    if (modal) {
        modal.remove();
    }
}

// ===================================================================
// GLOBAL POOL HEALTH DASHBOARD
// ===================================================================

/**
 * Show global pool health dashboard
 */
async function showPoolHealthDashboard() {
    console.log('Loading global pool health dashboard');
    
    const healthEndpoint = `${window.ROOT_PATH}/servers/pools/health`;
    console.log(`Fetching from: ${healthEndpoint}`);
    
    const response = await fetchWithTimeout(healthEndpoint);
    
    if (!response.ok) {
        console.error(`API error: ${response.status} ${response.statusText}`);
        // Provide helpful error message if endpoint has server issues
        if (response.status === 500) {
            showPoolNotification('Pool manager not available - check server configuration', 'error');
        } else if (response.status === 503) {
            showPoolNotification('Pool service temporarily unavailable', 'error');
        } else {
            showPoolNotification('Failed to load pool health dashboard', 'error');
        }
        return;
    }
    
    try {
        const data = await response.json();
        console.log('Health data loaded:', data);
        
        // Normalize the response to match expected format
        const health = {
            overall_health: (data.overall_health_score >= 70) ? 'healthy' : 
                           (data.overall_health_score >= 50) ? 'degraded' : 'unhealthy',
            total_pools: data.total_pools || 0,
            pools: (data.pools || []).map(pool => ({
                server_id: pool.server_id,
                server_name: pool.server_id, // Use server_id as name since it's not provided
                health_status: pool.status === 'healthy' ? 'healthy' : 
                              pool.status === 'degraded' ? 'degraded' : 'unhealthy',
                total_sessions: pool.total_sessions || 0,
                active_sessions: pool.active_sessions || 0,
                success_rate: (pool.health_score || 0) / 100
            }))
        };
        
        // Show dashboard modal
        showPoolHealthModal(health);
    } catch (error) {
        console.error('Error parsing health dashboard:', error);
        showPoolNotification('Failed to parse pool health dashboard', 'error');
    }
}

/**
 * Display pool health dashboard modal
 * @param {Object} health - Global health data
 */
function showPoolHealthModal(health) {
    const modal = document.createElement('div');
    modal.id = 'pool-health-modal';
    modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
    
    const poolsHtml = health.pools.map(pool => {
        const healthColor = pool.health_status === 'healthy' ? 'green' : 
                           pool.health_status === 'degraded' ? 'yellow' : 'red';
        
        return `
            <div class="p-4 bg-white dark:bg-gray-700 rounded-lg shadow">
                <div class="flex justify-between items-start mb-2">
                    <h4 class="font-semibold text-gray-900 dark:text-gray-100">${pool.server_name}</h4>
                    <span class="px-2 py-1 rounded-full text-xs font-medium bg-${healthColor}-100 text-${healthColor}-800 dark:bg-${healthColor}-900 dark:text-${healthColor}-300">
                        ${pool.health_status}
                    </span>
                </div>
                <div class="grid grid-cols-3 gap-2 text-sm">
                    <div>
                        <p class="text-gray-600 dark:text-gray-400">Total</p>
                        <p class="font-semibold text-gray-900 dark:text-gray-100">${pool.total_sessions}</p>
                    </div>
                    <div>
                        <p class="text-gray-600 dark:text-gray-400">Active</p>
                        <p class="font-semibold text-gray-900 dark:text-gray-100">${pool.active_sessions}</p>
                    </div>
                    <div>
                        <p class="text-gray-600 dark:text-gray-400">Success</p>
                        <p class="font-semibold text-gray-900 dark:text-gray-100">${(pool.success_rate * 100).toFixed(1)}%</p>
                    </div>
                </div>
                <button onclick="showPoolStats('${pool.server_id}')" 
                        class="mt-2 w-full px-3 py-1 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md">
                    View Details
                </button>
            </div>
        `;
    }).join('');
    
    modal.innerHTML = `
        <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-6xl shadow-lg rounded-md bg-white dark:bg-gray-800">
            <div class="flex justify-between items-center pb-3 border-b dark:border-gray-700">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    🏥 Pool Health Dashboard
                </h3>
                <button onclick="closePoolHealthModal()" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            
            <div class="mt-4">
                <!-- Overall Health -->
                <div class="mb-6 p-4 bg-${health.overall_health === 'healthy' ? 'green' : health.overall_health === 'degraded' ? 'yellow' : 'red'}-50 dark:bg-${health.overall_health === 'healthy' ? 'green' : health.overall_health === 'degraded' ? 'yellow' : 'red'}-900/20 rounded-lg">
                    <div class="flex justify-between items-center">
                        <div>
                            <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Overall Health</p>
                            <p class="text-2xl font-bold text-${health.overall_health === 'healthy' ? 'green' : health.overall_health === 'degraded' ? 'yellow' : 'red'}-600 dark:text-${health.overall_health === 'healthy' ? 'green' : health.overall_health === 'degraded' ? 'yellow' : 'red'}-400 capitalize">
                                ${health.overall_health}
                            </p>
                        </div>
                        <div class="text-right">
                            <p class="text-sm text-gray-600 dark:text-gray-400">Total Pools</p>
                            <p class="text-2xl font-bold text-gray-900 dark:text-gray-100">${health.total_pools}</p>
                        </div>
                    </div>
                </div>
                
                <!-- Individual Pools -->
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    ${poolsHtml || '<p class="col-span-full text-center text-gray-500 dark:text-gray-400">No pools configured</p>'}
                </div>
            </div>
            
            <div class="flex justify-end pt-4 border-t dark:border-gray-700 mt-4">
                <button onclick="closePoolHealthModal()" 
                        class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-md">
                    Close
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/**
 * Close pool health modal
 */
function closePoolHealthModal() {
    const modal = document.getElementById('pool-health-modal');
    if (modal) {
        modal.remove();
    }
}

// ===================================================================
// UTILITY FUNCTIONS
// ===================================================================

/**
 * Show notification message for pool management
 * Bulletproof implementation - cannot throw or cause recursion
 * @param {string} message - The message to display
 * @param {string} type - The notification type (success, error, info)
 */
function showPoolNotification(message, type = 'info') {
    // Immediate guard: exit if called recursively
    if (window.__poolNotificationInProgress) {
        return;
    }
    
    // Set recursion guard
    window.__poolNotificationInProgress = true;
    
    try {
        // Validate inputs defensively
        if (typeof message !== 'string' || !message.trim()) {
            console.warn('showPoolNotification: Invalid or empty message');
            return;
        }
        
        if (typeof type !== 'string') {
            type = 'info';
        }
        
        // Validate document is available
        if (!document || !document.body) {
            console.warn('showPoolNotification: Document not ready');
            return;
        }
        
        // Determine color class safely
        let bgColor = 'bg-blue-500';
        if (type === 'success') {
            bgColor = 'bg-green-500';
        } else if (type === 'error') {
            bgColor = 'bg-red-500';
        }
        
        // Create notification element with minimal dependencies
        const notification = document.createElement('div');
        notification.style.position = 'fixed';
        notification.style.top = '1rem';
        notification.style.right = '1rem';
        notification.style.zIndex = '50';
        notification.style.padding = '0.75rem 1.5rem';
        notification.style.borderRadius = '0.5rem';
        notification.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1)';
        notification.style.color = 'white';
        notification.style.fontSize = '0.875rem';
        notification.style.fontWeight = '500';
        notification.style.fontFamily = 'sans-serif';
        notification.style.maxWidth = '20rem';
        notification.style.wordWrap = 'break-word';
        
        // Apply background color with fallback
        if (bgColor === 'bg-green-500') {
            notification.style.backgroundColor = '#22c55e';
        } else if (bgColor === 'bg-red-500') {
            notification.style.backgroundColor = '#ef4444';
        } else {
            notification.style.backgroundColor = '#3b82f6';
        }
        
        notification.textContent = message.substring(0, 200);
        
        // Append to body
        document.body.appendChild(notification);
        
        // Auto-remove after 3 seconds with defensive removal
        setTimeout(() => {
            try {
                if (notification && notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            } catch (e) {
                // Silently ignore removal errors
            }
        }, 3000);
        
    } catch (error) {
        // Absolute last resort - only console.error, nothing else
        if (console && console.error) {
            try {
                console.error('showPoolNotification failed:', error.message);
            } catch (e) {
                // Ignore console error
            }
        }
    } finally {
        // Always clear the recursion guard
        window.__poolNotificationInProgress = false;
    }
}

/**
 * Fetch with timeout - uses native fetch with AbortController
 * Guaranteed to never throw - returns error response objects instead
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options
 * @param {number} timeout - Timeout in milliseconds (default 30s)
 * @returns {Promise} Always resolves with response object (never rejects)
 */
async function fetchWithTimeout(url, options = {}, timeout = 30000) {
    let timeoutId = null;
    const controller = new AbortController();
    
    try {
        // Guard against invalid inputs
        if (typeof url !== 'string' || !url.trim()) {
            return {
                ok: false,
                status: 400,
                statusText: 'Invalid URL',
                json: async () => ({ error: 'Invalid URL' })
            };
        }
        
        // Set up timeout that aborts the fetch
        timeoutId = setTimeout(() => {
            try {
                controller.abort();
            } catch (err) {
                // Silently ignore abort errors
            }
        }, timeout);
        
        // Perform the actual fetch
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });
        
        // Always clear the timeout
        if (timeoutId !== null) {
            clearTimeout(timeoutId);
        }
        
        return response;
    } catch (error) {
        // Always clear the timeout on error
        if (timeoutId !== null) {
            clearTimeout(timeoutId);
        }
        
        // Log error but don't throw
        try {
            const errorMsg = error && error.message ? error.message : 'Unknown error';
            if (console && console.error) {
                console.error(`fetchWithTimeout error for ${url}:`, errorMsg);
            }
        } catch (e) {
            // Ignore logging errors
        }
        
        // Return synthetic error response object (never throws)
        return {
            ok: false,
            status: 0,
            statusText: (error && error.message) || 'Network error',
            json: async () => ({ error: (error && error.message) || 'Network error' })
        };
    }
}
// ===================================================================
// POOL CONTROL OPERATIONS
// ===================================================================

/**
 * Drain a pool - prevents new session acquisitions
 * @param {string} serverId - The server ID
 */
async function drainPool(serverId) {
    console.log(`Draining pool for server: ${serverId}`);
    
    if (!confirm('Drain this pool? This will prevent new session acquisitions while allowing existing sessions to complete.')) {
        return;
    }
    
    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/servers/${serverId}/pool/drain`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            }
        );
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            showPoolNotification(`Failed to drain pool: ${error.detail || response.statusText}`, 'error');
            return;
        }
        
        const result = await response.json();
        showPoolNotification(result.message || 'Pool drained successfully', 'success');
        
        // Refresh stats if modal is open
        if (window.currentPoolStatsServerId === serverId) {
            await refreshPoolStats(serverId);
        }
    } catch (error) {
        console.error('Error draining pool:', error);
        showPoolNotification('Failed to drain pool', 'error');
    }
}

/**
 * Resize a pool dynamically
 * @param {string} serverId - The server ID
 */
async function resizePool(serverId) {
    console.log(`Resizing pool for server: ${serverId}`);
    
    const newSize = prompt('Enter new pool size (1-1000):', '100');
    if (!newSize) {
        return; // User cancelled
    }
    
    const size = parseInt(newSize);
    if (isNaN(size) || size < 1 || size > 1000) {
        showPoolNotification('Invalid pool size. Must be between 1 and 1000.', 'error');
        return;
    }
    
    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/servers/${serverId}/pool/resize?size=${size}`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            },
            120000  // 2 minute timeout for resize operations
        );
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            showPoolNotification(`Failed to resize pool: ${error.detail || response.statusText}`, 'error');
            return;
        }
        
        const stats = await response.json();
        showPoolNotification(`Pool resized to ${size} sessions`, 'success');
        
        // Refresh stats if modal is open
        if (window.currentPoolStatsServerId === serverId) {
            await refreshPoolStats(serverId);
        }
    } catch (error) {
        console.error('Error resizing pool:', error);
        showPoolNotification('Failed to resize pool', 'error');
    }
}

/**
 * Reset a pool - closes all sessions and recreates the pool
 * @param {string} serverId - The server ID
 */
async function resetPool(serverId) {
    console.log(`Resetting pool for server: ${serverId}`);
    
    if (!confirm('Reset this pool? This will close ALL sessions and recreate the pool from scratch. Active connections will be terminated.')) {
        return;
    }
    
    try {
        const response = await fetchWithTimeout(
            `${window.ROOT_PATH}/servers/${serverId}/pool/reset`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            }
        );
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            showPoolNotification(`Failed to reset pool: ${error.detail || response.statusText}`, 'error');
            return;
        }
        
        const result = await response.json();
        showPoolNotification(result.message || 'Pool reset successfully', 'success');
        
        // Refresh stats if modal is open
        if (window.currentPoolStatsServerId === serverId) {
            await refreshPoolStats(serverId);
        }
    } catch (error) {
        console.error('Error resetting pool:', error);
        showPoolNotification('Failed to reset pool', 'error');
    }
}

console.log('Pool management UI loaded - v2.0.1');

// Made with Bob
