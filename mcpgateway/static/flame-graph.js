/**
 * Interactive Flame Graph for Trace Visualization
 *
 * Features:
 * - Stack-based visualization showing execution hierarchy
 * - Click to zoom into specific spans
 * - Search and highlight functionality
 * - Hover tooltips with span details
 * - Color-coding by span type
 */

/* eslint-disable no-unused-vars */
class FlameGraph {
  constructor(containerId, traceData) {
    this.container = document.getElementById(containerId);
    this.trace = traceData;
    this.spans = this.buildSpanTree(traceData.spans);
    this.width = 0;
    this.height = 0;
    this.cellHeight = 20;
    this.textPadding = 5;
    this.rootNode = null;
    this.currentRoot = null;
    this.searchTerm = "";

    this.init();
  }

  /**
   * Build hierarchical span tree from flat span list
   */
  buildSpanTree(spans) {
    const spanMap = new Map();
    let rootSpan = null;

    // Create map of all spans
    spans.forEach((span) => {
      spanMap.set(span.span_id, {
        ...span,
        children: [],
      });
    });

    // Build tree structure
    spans.forEach((span) => {
      const node = spanMap.get(span.span_id);
      if (span.parent_span_id && spanMap.has(span.parent_span_id)) {
        const parent = spanMap.get(span.parent_span_id);
        parent.children.push(node);
      } else {
        // This is a root node
        if (!rootSpan || node.start_time < rootSpan.start_time) {
          rootSpan = node;
        }
      }
    });

    // Calculate total duration for each node (self + children)
    const calculateTotalDuration = (node) => {
      const total = node.duration_ms || 0;
      node.children.forEach((child) => {
        calculateTotalDuration(child);
      });
      node.totalDuration = total;
      return total;
    };

    if (rootSpan) {
      calculateTotalDuration(rootSpan);
    }

    return rootSpan;
  }

  /**
   * Initialize the flame graph
   */
  init() {
    this.rootNode = this.spans;
    this.currentRoot = this.rootNode;
    this.render();
  }

  /**
   * Render the complete flame graph
   */
  render() {
    if (!this.rootNode) {
      this.container.innerHTML = `
                <div style="padding: 2rem; text-align: center; color: #6b7280;">
                    No span data available for flame graph
                </div>
            `;
      return;
    }

    // Calculate dimensions
    this.width = this.container.clientWidth || 800;
    const depth = this.calculateDepth(this.currentRoot);
    this.height = depth * this.cellHeight + 100;

    const html = `
            <div class="flame-graph-container">
                <!-- Toolbar -->
                <div class="flame-toolbar">
                    <div class="flame-info">
                        <strong>Flame Graph</strong>
                        <span style="margin-left: 1rem; color: #6b7280;">
                            ${this.currentRoot.name} - ${this.currentRoot.duration_ms?.toFixed(2) || 0} ms
                        </span>
                    </div>
                    <div class="flame-controls">
                        <input
                            type="text"
                            placeholder="Search spans..."
                            class="flame-search"
                            onkeyup="flameGraph.search(this.value)"
                            value="${this.searchTerm}"
                        />
                        <button onclick="flameGraph.reset()" class="flame-btn" title="Reset Zoom">
                            ⟲ Reset
                        </button>
                    </div>
                </div>

                <!-- SVG Canvas -->
                <svg class="flame-svg" width="${this.width}" height="${this.height}">
                    ${this.renderNode(this.currentRoot, 0, 0, this.width)}
                </svg>

                <!-- Legend -->
                <div class="flame-legend">
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
                    <div class="legend-item" style="font-size: 0.75rem; color: #6b7280; margin-left: 1rem;">
                        💡 Click on any span to zoom in
                    </div>
                </div>
            </div>
        `;

    this.container.innerHTML = html;
  }

  /**
   * Calculate the maximum depth of the tree
   */
  calculateDepth(node, currentDepth = 0) {
    if (!node || !node.children || node.children.length === 0) {
      return currentDepth + 1;
    }

    let maxDepth = currentDepth + 1;
    node.children.forEach((child) => {
      const childDepth = this.calculateDepth(child, currentDepth + 1);
      maxDepth = Math.max(maxDepth, childDepth);
    });

    return maxDepth;
  }

  /**
   * Render a single node and its children recursively
   */
  renderNode(node, x, y, width, parentDuration = null) {
    if (!node) {
      return "";
    }

    const duration = node.duration_ms || 0;
    const totalParentDuration = parentDuration || duration;

    // Calculate width based on duration percentage
    const nodeWidth = (duration / totalParentDuration) * width;

    if (nodeWidth < 0.5) {
      return ""; // Too small to render
    }

    // Determine color based on span kind and search
    const isSearchMatch =
      this.searchTerm &&
      node.name.toLowerCase().includes(this.searchTerm.toLowerCase());
    let color = this.getSpanColor(node);

    if (isSearchMatch) {
      color = "#f59e0b"; // Highlight search matches in orange
    }

    // Truncate text if too long for the box
    const availableWidth = nodeWidth - this.textPadding * 2;
    const charWidth = 7; // Approximate character width
    const maxChars = Math.floor(availableWidth / charWidth);
    let displayText = node.name;

    if (displayText.length > maxChars && maxChars > 3) {
      displayText = displayText.substring(0, maxChars - 3) + "...";
    }

    // Generate SVG rectangle with text
    let svg = `
            <g class="flame-node ${isSearchMatch ? "search-match" : ""}"
               data-span-id="${node.span_id}"
               onclick="flameGraph.zoomTo('${node.span_id}')"
               style="cursor: pointer;">
                <rect
                    x="${x}"
                    y="${y}"
                    width="${nodeWidth}"
                    height="${this.cellHeight - 1}"
                    fill="${color}"
                    stroke="#fff"
                    stroke-width="1"
                    rx="2"
                />
                <title>${node.name}\nDuration: ${duration.toFixed(2)}ms\nKind: ${node.kind}\nStatus: ${node.status}</title>
                ${
  nodeWidth > 30
    ? `<text
                    x="${x + this.textPadding}"
                    y="${y + this.cellHeight / 2 + 4}"
                    fill="#fff"
                    font-size="12"
                    font-family="system-ui, -apple-system, sans-serif"
                    pointer-events="none"
                >${displayText} (${duration.toFixed(1)}ms)</text>`
    : ""
}
            </g>
        `;

    // Render children below this node
    if (node.children && node.children.length > 0) {
      let childX = x;

      node.children.forEach((child) => {
        const childDuration = child.duration_ms || 0;
        const childWidth = (childDuration / duration) * nodeWidth;

        svg += this.renderNode(
          child,
          childX,
          y + this.cellHeight,
          childWidth,
          duration
        );

        childX += childWidth;
      });
    }

    return svg;
  }

  /**
   * Get color for a span based on its kind and status
   */
  getSpanColor(span) {
    if (span.status === "error") {
      return "#ef4444"; // red
    }

    switch (span.kind) {
      case "client":
        return "#3b82f6"; // blue
      case "server":
        return "#10b981"; // green
      case "internal":
        return "#8b5cf6"; // purple
      default:
        return "#6b7280"; // gray
    }
  }

  /**
   * Find node by span_id
   */
  findNode(node, spanId) {
    if (node.span_id === spanId) {
      return node;
    }

    if (node.children) {
      for (const child of node.children) {
        const found = this.findNode(child, spanId);
        if (found) {
          return found;
        }
      }
    }

    return null;
  }

  /**
   * Zoom to a specific node
   */
  zoomTo(spanId) {
    const node = this.findNode(this.rootNode, spanId);
    if (node) {
      this.currentRoot = node;
      this.render();
    }
  }

  /**
   * Reset zoom to root
   */
  reset() {
    this.currentRoot = this.rootNode;
    this.searchTerm = "";
    this.render();
  }

  /**
   * Search for spans by name
   */
  search(term) {
    this.searchTerm = term;
    this.render();
  }
}

// Global instance (will be initialized from template)
// eslint-disable-next-line prefer-const
let flameGraph = null;

// Support ES module imports (tests) while remaining a plain <script> in the browser
 
if (typeof exports !== "undefined") { exports.FlameGraph = FlameGraph; }
