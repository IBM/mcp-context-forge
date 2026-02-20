// ===================================================================
// PAGINATION COMPONENT
// Defined once here so all pagination_controls.html includes share
// a single global definition. Each Alpine instance reads its own
// per-section data from HTML data-* attributes in init().
//
// Extra query params (search terms, filters) that vary per-section are
// registered via tojson-escaped <script> blocks in pagination_controls.html
// and stored here under the section's table_name key.
// ===================================================================

import { AppState } from "./appState";
import { safeReplaceState } from "./security";

export function paginationData() {
  return {
    // Defaults; all overwritten by init() from data-* attributes.
    currentPage: 1,
    perPage: 10,
    totalItems: 0,
    totalPages: 0,
    hasNext: false,
    hasPrev: false,
    targetSelector: "#tools-table",
    swapStyle: "innerHTML",
    tableName: "",
    baseUrl: "",
    indicator: "#loading",

    // Alpine lifecycle hook — called automatically when the component mounts.
    // Reads per-instance values from this element's data-* attributes so that
    // multiple components on the same page each get their own correct data.
    init() {
      const el = this.$el;
      this.currentPage = parseInt(el.dataset.currentPage, 10) || 1;
      this.perPage = parseInt(el.dataset.perPage, 10) || 10;
      this.totalItems = parseInt(el.dataset.totalItems, 10) || 0;
      this.totalPages = parseInt(el.dataset.totalPages, 10) || 0;
      this.hasNext = el.dataset.hasNext === "true";
      this.hasPrev = el.dataset.hasPrev === "true";
      this.targetSelector = el.dataset.hxTarget || "#tools-table";
      this.swapStyle = el.dataset.hxSwap || "innerHTML";
      this.tableName = el.dataset.tableName || "";
      this.baseUrl = el.dataset.baseUrl || "";
      this.indicator = el.dataset.hxIndicator || "#loading";

      // Honour namespaced URL param for page size (bookmarked / shared URLs).
      if (this.tableName) {
        const urlParams = new URLSearchParams(window.location.search);
        const urlPageSize = parseInt(
          urlParams.get(this.tableName + "_size"),
          10
        );
        if (urlPageSize && [10, 25, 50, 100, 200, 500].includes(urlPageSize)) {
          this.perPage = urlPageSize;
        }
      }
    },

    goToPage(page) {
      if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
        this.currentPage = page;
        this.loadPage(page);
      }
    },

    prevPage() {
      if (this.hasPrev) {
        this.goToPage(this.currentPage - 1);
      }
    },

    nextPage() {
      if (this.hasNext) {
        this.goToPage(this.currentPage + 1);
      }
    },

    changePageSize(size) {
      this.perPage = parseInt(size, 10);
      this.currentPage = 1;
      this.loadPage(1);
    },

    // Updates the browser address bar with namespaced pagination params so
    // that each table's state is independently bookmarkable / shareable.
    updateBrowserUrl(page, includeInactive) {
      if (!this.tableName) return;
      const currentUrl = new URL(window.location.href);
      const newParams = new URLSearchParams(currentUrl.searchParams);
      const prefix = this.tableName + "_";

      newParams.set(prefix + "page", page);
      newParams.set(prefix + "size", this.perPage);
      if (includeInactive !== undefined) {
        newParams.set(prefix + "inactive", includeInactive.toString());
      }

      const newUrl =
        currentUrl.pathname + "?" + newParams.toString() + currentUrl.hash;
      safeReplaceState({}, "", newUrl);
    },

    loadPage(page) {
      const url = new URL(this.baseUrl, window.location.origin);
      url.searchParams.set("page", page);
      url.searchParams.set("per_page", this.perPage);

      // Resolve the include_inactive checkbox for this section by deriving
      // its element ID from the HTMX target selector.
      // Examples:
      //   #servers-table          -> show-inactive-servers
      //   #servers-table-body     -> show-inactive-servers
      //   #resources-list-container -> show-inactive-resources
      //   #agents-table           -> show-inactive-a2a-agents
      let checkboxId = this.targetSelector
        .replace("#", "show-inactive-")
        .replace(/-table-body$/, "")
        .replace(/-table$/, "")
        .replace(/-list-container$/, "");
      if (checkboxId === "show-inactive-agents") {
        checkboxId = "show-inactive-a2a-agents";
      }
      const checkbox = document.getElementById(checkboxId);
      let includeInactive;
      if (checkbox) {
        includeInactive = checkbox.checked;
        url.searchParams.set("include_inactive", includeInactive.toString());
      }

      // Apply extra query params registered by the template's per-instance
      // <script> block (AppState._paginationQuerySetters[tableName]).
      // Each pagination_controls.html include that has query_params renders
      // a tojson-escaped setter function under its table_name key.
      const setter = AppState._paginationQuerySetters[this.tableName];
      if (setter) setter(url);

      // Preserve team_id filter from the current URL.
      const currentUrlParams = new URLSearchParams(window.location.search);
      const teamIdFromUrl = currentUrlParams.get("team_id");
      if (teamIdFromUrl) {
        url.searchParams.set("team_id", teamIdFromUrl);
      }

      this.updateBrowserUrl(page, includeInactive);

      // Scroll the target section into view before the fetch.
      const targetElement = document.querySelector(this.targetSelector);
      if (targetElement) {
        const panel = targetElement.closest(".tab-panel, .bg-white, .shadow");
        if (panel) {
          panel.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        } else {
          targetElement.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        }
      }

      // Trigger the HTMX fetch; indicator comes from data-hx-indicator.
      window.htmx.ajax("GET", url.toString(), {
        target: this.targetSelector,
        swap: this.swapStyle,
        indicator: this.indicator,
      });
    },
  };
}
