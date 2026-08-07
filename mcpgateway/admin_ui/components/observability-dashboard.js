/**
 * Observability dashboard Alpine component.
 *
 * Registered via Alpine.data() rather than declared inline in the template.
 * The admin UI uses the CSP-safe Alpine build (@alpinejs/csp), whose expression
 * parser accepts object literals of plain data only. A single function - method
 * shorthand or arrow - makes the whole x-data object fail to parse, and Alpine
 * then initialises the component as {} without throwing. Every field and method
 * reads as "Undefined variable", x-init never runs, and the panel stays empty
 * while issuing no network requests at all.
 *
 * Defining the object here keeps the functions out of the attribute parser.
 */
export function observabilityDashboard() {
  return {
      viewMode: 'traces',
      selectedTrace: null,
      timeRange: '24h',
      statusFilter: 'all',
      minDuration: '',
      maxDuration: '',
      httpMethod: '',
      userEmail: '',
      nameSearch: '',
      attributeSearch: '',
      toolName: '',
      showAdvancedFilters: false,
      loading: false,
      stats: {},
      tracesInterval: null,
      statsInterval: null,
      savedQueries: [],
      selectedQueryId: '',
      showSaveQueryModal: false,
      saveQueryName: '',
      saveQueryDescription: '',
      saveQueryIsShared: false,
      metricsLoaded: false,
      toolsLoaded: false,
      promptsLoaded: false,
      resourcesLoaded: false,
      metricsLoading: false,
      toolsLoading: false,
      promptsLoading: false,
      resourcesLoading: false,
      async loadMetricsView() {
          // Only load once, but allow retry if previous load was interrupted
          if (this.metricsLoaded) {
              console.log('Metrics view already loaded, skipping fetch');
              return;
          }

          // Prevent concurrent loads
          if (this.metricsLoading) {
              console.log('Metrics view already loading, skipping');
              return;
          }

          this.metricsLoading = true;
          console.log('Loading metrics view for the first time...');

          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/metrics/partial');
              if (response.ok) {
                  // Check if still on metrics view before rendering
                  if (this.viewMode !== 'metrics') {
                      console.log('View changed during fetch, aborting metrics load');
                      this.metricsLoading = false;
                      return;
                  }

                  const html = await response.text();
                  const container = document.getElementById('metrics-container');
                  if (!container) {
                      console.warn('Metrics container not found');
                      this.metricsLoading = false;
                      return;
                  }

                  // Extract scripts from raw text and execute synchronously,
                  // then get clean HTML without <script> tags
                  const cleanHtml = window.__obsExecAndStrip(html);

                  // Insert script-free HTML with Alpine MutationObserver disabled,
                  // then explicitly initialize Alpine components
                  if (window.Alpine && typeof window.Alpine.mutateDom === 'function' && typeof window.Alpine.initTree === 'function') {
                      window.Alpine.mutateDom(() => {
                          container.innerHTML = cleanHtml;
                      });
                      window.Alpine.initTree(container);
                  } else {
                      container.innerHTML = cleanHtml;
                  }

                  // Only mark as loaded if we're still on the metrics view
                  if (this.viewMode === 'metrics') {
                      this.metricsLoaded = true;
                      console.log('Metrics view loaded successfully');
                  } else {
                      console.log('View changed after render, not marking as loaded');
                  }
              }
          } catch (error) {
              console.error('Failed to load metrics view:', error);
          } finally {
              this.metricsLoading = false;
          }
      },
      async loadToolsView() {
          // Only load once, but allow retry if previous load was interrupted
          if (this.toolsLoaded) {
              console.log('Tools view already loaded, skipping fetch');
              return;
          }

          // Prevent concurrent loads
          if (this.toolsLoading) {
              console.log('Tools view already loading, skipping');
              return;
          }

          this.toolsLoading = true;
          console.log('Loading tools view for the first time...');

          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/tools/partial');
              if (response.ok) {
                  // Check if still on tools view before rendering
                  if (this.viewMode !== 'tools') {
                      console.log('View changed during fetch, aborting tools load');
                      this.toolsLoading = false;
                      return;
                  }

                  const html = await response.text();
                  const container = document.getElementById('tools-container');
                  if (!container) {
                      console.warn('Tools container not found');
                      this.toolsLoading = false;
                      return;
                  }

                  const cleanHtml = window.__obsExecAndStrip(html);

                  if (window.Alpine && typeof window.Alpine.mutateDom === 'function' && typeof window.Alpine.initTree === 'function') {
                      window.Alpine.mutateDom(() => {
                          container.innerHTML = cleanHtml;
                      });
                      window.Alpine.initTree(container);
                  } else {
                      container.innerHTML = cleanHtml;
                  }

                  // Only mark as loaded if we're still on the tools view
                  if (this.viewMode === 'tools') {
                      this.toolsLoaded = true;
                      console.log('Tools view loaded successfully');
                  } else {
                      console.log('View changed after render, not marking as loaded');
                  }
              }
          } catch (error) {
              console.error('Failed to load tools view:', error);
          } finally {
              this.toolsLoading = false;
          }
      },
      async loadPromptsView() {
          // Only load once, but allow retry if previous load was interrupted
          if (this.promptsLoaded) {
              console.log('Prompts view already loaded, skipping fetch');
              return;
          }

          // Prevent concurrent loads
          if (this.promptsLoading) {
              console.log('Prompts view already loading, skipping');
              return;
          }

          this.promptsLoading = true;
          console.log('Loading prompts view for the first time...');

          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/prompts/partial');
              if (response.ok) {
                  // Check if still on prompts view before rendering
                  if (this.viewMode !== 'prompts') {
                      console.log('View changed during fetch, aborting prompts load');
                      this.promptsLoading = false;
                      return;
                  }

                  const html = await response.text();
                  const container = document.getElementById('prompts-container');
                  if (!container) {
                      console.warn('Prompts container not found');
                      this.promptsLoading = false;
                      return;
                  }

                  const cleanHtml = window.__obsExecAndStrip(html);

                  if (window.Alpine && typeof window.Alpine.mutateDom === 'function' && typeof window.Alpine.initTree === 'function') {
                      window.Alpine.mutateDom(() => {
                          container.innerHTML = cleanHtml;
                      });
                      window.Alpine.initTree(container);
                  } else {
                      container.innerHTML = cleanHtml;
                  }

                  // Only mark as loaded if we're still on the prompts view
                  if (this.viewMode === 'prompts') {
                      this.promptsLoaded = true;
                      console.log('Prompts view loaded successfully');
                  } else {
                      console.log('View changed after render, not marking as loaded');
                  }
              }
          } catch (error) {
              console.error('Failed to load prompts view:', error);
          } finally {
              this.promptsLoading = false;
          }
      },
      async loadResourcesView() {
          // Only load once, but allow retry if previous load was interrupted
          if (this.resourcesLoaded) {
              console.log('Resources view already loaded, skipping fetch');
              return;
          }

          // Prevent concurrent loads
          if (this.resourcesLoading) {
              console.log('Resources view already loading, skipping');
              return;
          }

          this.resourcesLoading = true;
          console.log('Loading resources view for the first time...');

          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/resources/partial');
              if (response.ok) {
                  // Check if still on resources view before rendering
                  if (this.viewMode !== 'resources') {
                      console.log('View changed during fetch, aborting resources load');
                      this.resourcesLoading = false;
                      return;
                  }

                  const html = await response.text();
                  const container = document.getElementById('resources-container');
                  if (!container) {
                      console.warn('Resources container not found');
                      this.resourcesLoading = false;
                      return;
                  }

                  const cleanHtml = window.__obsExecAndStrip(html);

                  if (window.Alpine && typeof window.Alpine.mutateDom === 'function' && typeof window.Alpine.initTree === 'function') {
                      window.Alpine.mutateDom(() => {
                          container.innerHTML = cleanHtml;
                      });
                      window.Alpine.initTree(container);
                  } else {
                      container.innerHTML = cleanHtml;
                  }

                  // Only mark as loaded if we're still on the resources view
                  if (this.viewMode === 'resources') {
                      this.resourcesLoaded = true;
                      console.log('Resources view loaded successfully');
                  } else {
                      console.log('View changed after render, not marking as loaded');
                  }
              }
          } catch (error) {
              console.error('Failed to load resources view:', error);
          } finally {
              this.resourcesLoading = false;
          }
      },
      refreshTraces() {
          let url = `${window.ROOT_PATH || ''}/admin/observability/traces?time_range=${this.timeRange}&status_filter=${this.statusFilter}&limit=50`;
          if (this.minDuration) url += `&min_duration=${this.minDuration}`;
          if (this.maxDuration) url += `&max_duration=${this.maxDuration}`;
          if (this.httpMethod) url += `&http_method=${this.httpMethod}`;
          if (this.userEmail) url += `&user_email=${encodeURIComponent(this.userEmail)}`;
          if (this.nameSearch) url += `&name_search=${encodeURIComponent(this.nameSearch)}`;
          if (this.attributeSearch) url += `&attribute_search=${encodeURIComponent(this.attributeSearch)}`;
          if (this.toolName) url += `&tool_name=${encodeURIComponent(this.toolName)}`;
          htmx.ajax('GET', url, {target: '#traces-list', swap: 'innerHTML'});
      },
      refreshStats() {
          htmx.ajax('GET', (window.ROOT_PATH || '') + '/admin/observability/stats', {target: '#stats-container', swap: 'innerHTML'});
      },
      startPolling() {
          this.refreshTraces();
          this.refreshStats();
          this.tracesInterval = setInterval(() => this.refreshTraces(), 5000);
          this.statsInterval = setInterval(() => this.refreshStats(), 30000);
      },
      stopPolling() {
          if (this.tracesInterval) clearInterval(this.tracesInterval);
          if (this.statsInterval) clearInterval(this.statsInterval);
      },
      applyFilters() {
          this.stopPolling();
          this.refreshTraces();
          this.startPolling();
      },
      refreshAll() {
          this.refreshStats();
          this.refreshTraces();
      },
      setViewMode(mode) {
          this.viewMode = mode;
          if (mode === 'metrics') { this.loadMetricsView(); }
          else if (mode === 'tools') { this.loadToolsView(); }
          else if (mode === 'prompts') { this.loadPromptsView(); }
          else if (mode === 'resources') { this.loadResourcesView(); }
      },
      clearFilters() {
          this.minDuration = '';
          this.maxDuration = '';
          this.httpMethod = '';
          this.userEmail = '';
          this.nameSearch = '';
          this.attributeSearch = '';
          this.refreshTraces();
      },
      async loadSavedQueries() {
          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/queries');
              if (response.ok) {
                  this.savedQueries = await response.json();
              }
          } catch (e) {
              console.error('Failed to load saved queries:', e);
          }
      },
      async applySavedQuery() {
          if (!this.selectedQueryId) return;
          try {
              const response = await fetch(`${window.ROOT_PATH || ''}/admin/observability/queries/${this.selectedQueryId}`);
              if (response.ok) {
                  const query = await response.json();
                  const config = query.filter_config;
                  this.timeRange = config.timeRange || '24h';
                  this.statusFilter = config.statusFilter || 'all';
                  this.minDuration = config.minDuration || '';
                  this.maxDuration = config.maxDuration || '';
                  this.toolName = config.toolName || '';
                  this.httpMethod = config.httpMethod || '';
                  this.userEmail = config.userEmail || '';
                  this.nameSearch = config.nameSearch || '';
                  this.attributeSearch = config.attributeSearch || '';
                  this.applyFilters();
                  // Track usage
                  await fetch(`${window.ROOT_PATH || ''}/admin/observability/queries/${this.selectedQueryId}/use`, { method: 'POST' });
              }
          } catch (e) {
              console.error('Failed to apply saved query:', e);
          }
      },
      getCurrentFilterConfig() {
          return {
              timeRange: this.timeRange,
              statusFilter: this.statusFilter,
              minDuration: this.minDuration,
              maxDuration: this.maxDuration,
              httpMethod: this.httpMethod,
              userEmail: this.userEmail,
              nameSearch: this.nameSearch,
              attributeSearch: this.attributeSearch,
              toolName: this.toolName
          };
      },
      async saveCurrentQuery() {
          if (!this.saveQueryName) {
              alert('Please enter a name for the query');
              return;
          }
          try {
              const response = await fetch((window.ROOT_PATH || '') + '/admin/observability/queries', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                      name: this.saveQueryName,
                      description: this.saveQueryDescription,
                      filter_config: this.getCurrentFilterConfig(),
                      is_shared: this.saveQueryIsShared
                  })
              });
              if (response.ok) {
                  this.showSaveQueryModal = false;
                  this.saveQueryName = '';
                  this.saveQueryDescription = '';
                  this.saveQueryIsShared = false;
                  await this.loadSavedQueries();
                  alert('Query saved successfully!');
              } else {
                  alert('Failed to save query');
              }
          } catch (e) {
              console.error('Failed to save query:', e);
              alert('Failed to save query');
          }
      },
      async deleteSavedQuery(queryId) {
          if (!confirm('Are you sure you want to delete this saved query?')) return;
          try {
              const response = await fetch(`${window.ROOT_PATH || ''}/admin/observability/queries/${queryId}`, { method: 'DELETE' });
              if (response.ok) {
                  await this.loadSavedQueries();
                  if (this.selectedQueryId == queryId) {
                      this.selectedQueryId = '';
                  }
              }
          } catch (e) {
              console.error('Failed to delete query:', e);
          }
      },
      resetLoadedFlags() {
          // Reset loaded flags so partials will reload when returning to the tab
          this.metricsLoaded = false;
          this.toolsLoaded = false;
          this.promptsLoaded = false;
          this.resourcesLoaded = false;
          console.log('Observability loaded flags reset');
      },

    /**
     * Alpine lifecycle hook, replacing the template's former x-init attribute.
     */
    init() {
      this.startPolling();
      this.loadSavedQueries();
      this.$watch('timeRange', () => this.applyFilters());
      this.$watch('statusFilter', () => this.applyFilters());
      this.$watch('minDuration', () => this.applyFilters());
      this.$watch('maxDuration', () => this.applyFilters());
      this.$watch('httpMethod', () => this.applyFilters());
      this.$watch('userEmail', () => this.applyFilters());
      this.$watch('nameSearch', () => this.applyFilters());
      this.$watch('attributeSearch', () => this.applyFilters());
      this.$watch('toolName', () => this.applyFilters());
      this.$watch('selectedQueryId', () => this.applySavedQuery());
    },
  };
}
