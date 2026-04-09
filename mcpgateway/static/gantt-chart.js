/**
 * Interactive Gantt Chart for Trace Visualization
 *
 * Features:
 * - Hierarchical span tree with expand/collapse
 * - Interactive zoom and pan
 * - Time scale with markers
 * - Critical path highlighting
 * - Keyboard shortcuts
 * - Hover tooltips
 */

/* eslint-disable no-unused-vars */
class GanttChart {
  constructor(containerId, traceData) {
    this.container = document.getElementById(containerId);
    this.trace = traceData;
    this.zoomLevel = 1;
    this.panOffset = 0;
    this.collapsedSpans = new Set();
    this.spans = this.buildSpanTree(traceData.spans);
    this.criticalPath = this.calculateCriticalPath();

    this.init();
  }

  /**
   * Build hierarchical span tree from flat span list
   */
  buildSpanTree(spans) {
    const spanMap = new Map();
    const roots = [];

    // Create map of all spans
    spans.forEach((span) => {
      spanMap.set(span.span_id, {
        ...span,
        children: [],
        depth: 0,
      });
    });

    // Build tree structure
    spans.forEach((span) => {
      const node = spanMap.get(span.span_id);
      if (span.parent_span_id && spanMap.has(span.parent_span_id)) {
        const parent = spanMap.get(span.parent_span_id);
        parent.children.push(node);
        node.depth = parent.depth + 1;
      } else {
        roots.push(node);
      }
    });

    // Flatten tree for rendering (depth-first)
    const flatten = (node) => {
      const result = [node];
      if (!this.collapsedSpans.has(node.span_id)) {
        node.children.forEach((child) => {
          result.push(...flatten(child));
        });
      }
      return result;
    };

    return roots.flatMap(flatten);
  }

  /**
   * Calculate critical path (slowest sequential chain)
   */
  calculateCriticalPath() {
    const criticalSpans = new Set();

    const findCriticalPath = (spans) => {
      if (spans.length === 0) {
        return [];
      }

      // Find span with longest duration + children duration
      let maxPath = [];
      let maxDuration = 0;

      spans.forEach((span) => {
        const childPath = findCriticalPath(span.children);
        const totalDuration =
          (span.duration_ms || 0) +
          childPath.reduce((sum, s) => sum + (s.duration_ms || 0), 0);

        if (totalDuration > maxDuration) {
          maxDuration = totalDuration;
          maxPath = [span, ...childPath];
        }
      });

      return maxPath;
    };

    const roots = this.spans.filter((s) => !s.parent_span_id);
    const path = findCriticalPath(roots);
    path.forEach((span) => criticalSpans.add(span.span_id));

    return criticalSpans;
  }

  /**
   * Initialize the chart
   */
  init() {
    this.render();
    this.attachEventListeners();
  }

  /**
   * Render the complete chart
   */
  render() {
    const totalDuration = this.trace.duration_ms || 1;
    const traceStart = new Date(this.trace.start_time);

    const html = `
            <div class="gantt-container">
                <!-- Toolbar -->
                <div class="gantt-toolbar">
                    <div class="gantt-info">
                        <strong>Total Duration:</strong> ${totalDuration.toFixed(2)} ms
                        <span style="margin-left: 1rem; color: #6b7280;">
                            ${this.spans.length} spans
                        </span>
                    </div>
                    <div class="gantt-controls">
                        <button onclick="ganttChart.zoomIn()" class="gantt-btn" title="Zoom In (=)">🔍+</button>
                        <button onclick="ganttChart.zoomOut()" class="gantt-btn" title="Zoom Out (-)">🔍−</button>
                        <button onclick="ganttChart.resetZoom()" class="gantt-btn" title="Reset (0)">⟲</button>
                        <button onclick="ganttChart.expandAll()" class="gantt-btn" title="Expand All">▼</button>
                        <button onclick="ganttChart.collapseAll()" class="gantt-btn" title="Collapse All">▶</button>
                    </div>
                </div>

                <!-- Time Scale -->
                <div class="gantt-timescale">
                    ${this.renderTimeScale(totalDuration)}
                </div>

                <!-- Spans -->
                <div class="gantt-spans">
                    ${this.spans.map((span) => this.renderSpan(span, totalDuration, traceStart)).join("")}
                </div>

                <!-- Legend -->
                <div class="gantt-legend">
                    <div class="legend-item">
                        <span class="legend-color" style="background: #3b82f6;"></span>
                        <span>Client</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color" style="background: #10b981;"></span>
                        <span>Server</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color" style="background: #8b5cf6;"></span>
                        <span>Internal</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color" style="background: #ef4444;"></span>
                        <span>Error</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color critical-path"></span>
                        <span>Critical Path</span>
                    </div>
                </div>
            </div>
        `;

    this.container.innerHTML = html;
  }

  /**
   * Render time scale markers
   */
  renderTimeScale(totalDuration) {
    const markers = [];
    const step = this.calculateTimeStep(totalDuration);

    for (let t = 0; t <= totalDuration; t += step) {
      const percent = (t / totalDuration) * 100;
      markers.push(`
                <div class="time-marker" style="left: ${percent}%;">
                    <div class="time-tick"></div>
                    <div class="time-label">${t.toFixed(0)}ms</div>
                </div>
            `);
    }

    return markers.join("");
  }

  /**
   * Calculate appropriate time step for markers
   */
  calculateTimeStep(totalDuration) {
    if (totalDuration < 10) {
      return 1;
    }
    if (totalDuration < 50) {
      return 5;
    }
    if (totalDuration < 100) {
      return 10;
    }
    if (totalDuration < 500) {
      return 50;
    }
    if (totalDuration < 1000) {
      return 100;
    }
    if (totalDuration < 5000) {
      return 500;
    }
    return 1000;
  }

  /**
   * Render individual span row
   */
  renderSpan(span, totalDuration, traceStart) {
    const duration = span.duration_ms || 0;
    const startMs = new Date(span.start_time) - traceStart;
    const leftPercent =
      (startMs / totalDuration) * 100 * this.zoomLevel + this.panOffset;
    const widthPercent = (duration / totalDuration) * 100 * this.zoomLevel;

    const hasChildren = span.children && span.children.length > 0;
    const isCollapsed = this.collapsedSpans.has(span.span_id);
    const isCritical = this.criticalPath.has(span.span_id);

    // Determine color based on span kind
    let color = "#3b82f6"; // client (blue)
    if (span.kind === "server") {
      color = "#10b981"; // green
    }
    if (span.kind === "internal") {
      color = "#8b5cf6"; // purple
    }
    if (span.status === "error") {
      color = "#ef4444"; // red
    }

    const indentPx = span.depth * 20;

    return `
            <div class="span-row ${isCritical ? "critical-path-row" : ""}" data-span-id="${span.span_id}">
                <div class="span-name" style="padding-left: ${indentPx}px;">
                    ${
  hasChildren
    ? `
                        <button class="span-toggle" onclick="ganttChart.toggleSpan('${span.span_id}')">
                            ${isCollapsed ? "▶" : "▼"}
                        </button>
                    `
    : '<span class="span-spacer"></span>'
}
                    <span class="span-label" title="${span.name}">
                        ${span.name}
                    </span>
                </div>
                <div class="span-timeline">
                    <div class="span-bar ${isCritical ? "critical-path-bar" : ""}"
                         style="left: ${Math.max(0, leftPercent)}%;
                                width: ${widthPercent}%;
                                background: ${color};"
                         title="${span.name}\nDuration: ${duration.toFixed(2)}ms\nKind: ${span.kind}\nStatus: ${span.status}"
                         onclick="ganttChart.showSpanDetails('${span.span_id}')">
                        ${widthPercent > 5 ? `<span class="span-bar-label">${duration.toFixed(1)}ms</span>` : ""}
                    </div>
                </div>
                <div class="span-duration">${duration.toFixed(2)} ms</div>
            </div>
        `;
  }

  /**
   * Toggle span expand/collapse
   */
  toggleSpan(spanId) {
    if (this.collapsedSpans.has(spanId)) {
      this.collapsedSpans.delete(spanId);
    } else {
      this.collapsedSpans.add(spanId);
    }
    this.spans = this.buildSpanTree(this.trace.spans);
    this.render();
  }

  /**
   * Expand all spans
   */
  expandAll() {
    this.collapsedSpans.clear();
    this.spans = this.buildSpanTree(this.trace.spans);
    this.render();
  }

  /**
   * Collapse all spans to top level
   */
  collapseAll() {
    this.trace.spans.forEach((span) => {
      if (span.parent_span_id) {
        this.collapsedSpans.add(span.parent_span_id);
      }
    });
    this.spans = this.buildSpanTree(this.trace.spans);
    this.render();
  }

  /**
   * Zoom in
   */
  zoomIn() {
    this.zoomLevel = Math.min(this.zoomLevel * 1.5, 10);
    this.render();
  }

  /**
   * Zoom out
   */
  zoomOut() {
    this.zoomLevel = Math.max(this.zoomLevel / 1.5, 0.1);
    this.render();
  }

  /**
   * Reset zoom and pan
   */
  resetZoom() {
    this.zoomLevel = 1;
    this.panOffset = 0;
    this.render();
  }

  /**
   * Show detailed span information
   */
  showSpanDetails(spanId) {
    const span = this.trace.spans.find((s) => s.span_id === spanId);
    if (!span) {
      return;
    }

    alert(
      `Span Details:\n\nName: ${span.name}\nDuration: ${span.duration_ms}ms\nKind: ${span.kind}\nStatus: ${span.status}\n\nAttributes:\n${JSON.stringify(span.attributes, null, 2)}`
    );
  }

  /**
   * Attach keyboard and mouse event listeners
   */
  attachEventListeners() {
    document.addEventListener("keydown", (e) => {
      if (!this.container.isConnected) {
        return;
      }

      switch (e.key) {
        case "=":
        case "+":
          this.zoomIn();
          e.preventDefault();
          break;
        case "-":
        case "_":
          this.zoomOut();
          e.preventDefault();
          break;
        case "0":
          this.resetZoom();
          e.preventDefault();
          break;
      }
    });
  }
}

// Global instance (will be initialized from template)
// eslint-disable-next-line prefer-const
let ganttChart = null;

// Support ES module imports (tests) while remaining a plain <script> in the browser

if (typeof exports !== "undefined") { exports.GanttChart = GanttChart; }
