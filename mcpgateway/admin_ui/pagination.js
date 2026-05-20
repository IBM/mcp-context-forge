// ===================================================================
// PAGINATION COMPONENT
// Defined once here so all pagination_controls.html includes share
// a single global definition. Each Alpine instance reads its own
// per-section data from HTML data-* attributes in init().
//
// Extra query params (search terms, filters) that vary per-section are
// serialised by the backend into the `data-extra-params` JSON attribute on
// the pagination_controls.html root element, and read back here in init().
// AppState.paginationQuerySetters[tableName] is also honoured as an
// additional, programmatic hook for params that can only be computed at
// runtime (e.g. live form values).
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
    pageItems: null,
    extraParams: {},
    _loading: false,

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

      // Decode the server-rendered extra query params (search term `q`,
      // `tags`, `gateway_id`, etc.). Failure to parse must not break
      // pagination — we just fall back to no extra params.
      this.extraParams = {};
      const rawExtra = el.dataset.extraParams;
      if (rawExtra) {
        try {
          const parsed = JSON.parse(rawExtra);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            this.extraParams = parsed;
          }
        } catch (_e) {
          // Malformed JSON — ignore and fall back to no extra params.
          this.extraParams = {};
        }
      }

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
      // Prevent concurrent requests for the same pagination component.
      if (this._loading) return;
      // Bail out if the swap target was removed by a previous failed swap —
      // this breaks the infinite-error loop that follows htmx:swapError.
      if (!document.querySelector(this.targetSelector)) return;

      this._loading = true;

      // Register a single unlock that fires on whichever htmx event arrives
      // first (success or any failure mode). Using AbortController to clean
      // up the sibling listeners keeps the document free of leaked
      // {once:true} handlers when only one of them ever fires.
      //
      // Listeners are scoped to the swap target element (not document) so
      // that unrelated htmx swaps on the page don't prematurely unlock this
      // component's _loading guard. htmx events bubble, so target-scoped
      // listeners catch events from swaps directed at that element.
      //
      // `htmx:swapError` MUST be in this list — without it, a swap failure
      // (e.g. session expiry returning a full HTML login page that htmx
      // can't merge into the fragment target) would leave `_loading=true`
      // permanently and silently freeze pagination until page reload.
      const unlockController =
        typeof AbortController !== "undefined" ? new AbortController() : null;
      const unlock = () => {
        this._loading = false;
        if (unlockController) unlockController.abort();
      };
      const listenerOpts = unlockController
        ? { once: true, signal: unlockController.signal }
        : { once: true };
      const listenTarget = document.querySelector(this.targetSelector) || document;
      listenTarget.addEventListener("htmx:afterSettle",   unlock, listenerOpts);
      listenTarget.addEventListener("htmx:responseError", unlock, listenerOpts);
      listenTarget.addEventListener("htmx:sendError",     unlock, listenerOpts);
      listenTarget.addEventListener("htmx:swapError",     unlock, listenerOpts);

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

      // Apply server-rendered extra query params (search `q`, `tags`,
      // `gateway_id`, etc.) decoded from data-extra-params in init().
      // `include_inactive` is owned by the checkbox path above, so we skip
      // it here even when the backend echoes it into query_params.
      if (this.extraParams && typeof this.extraParams === "object") {
        Object.entries(this.extraParams).forEach(([k, v]) => {
          if (k === "include_inactive") return;
          if (v === null || v === undefined) return;
          url.searchParams.set(k, String(v));
        });
      }

      // Apply extra query params registered programmatically by templates
      // (AppState.paginationQuerySetters[tableName]). This runs after the
      // declarative `data-extra-params` block so JS-only params can
      // override the server snapshot when needed.
      const setter = AppState.paginationQuerySetters[this.tableName];
      if (setter) setter(url);

      // Preserve team_id filter from the current URL when the server
      // snapshot doesn't already include one.
      if (!url.searchParams.has("team_id")) {
        const currentUrlParams = new URLSearchParams(window.location.search);
        const teamIdFromUrl = currentUrlParams.get("team_id");
        if (teamIdFromUrl) {
          url.searchParams.set("team_id", teamIdFromUrl);
        }
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
