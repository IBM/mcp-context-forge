// ===================================================================
// PROXY-AWARE ADMIN NAVIGATION
// Derives admin base from window.location so that proxy-embedded
// deployments (where window.ROOT_PATH may be empty) preserve the
// proxy prefix in the navigated URL. Fixes #3321 and #3324.
// ===================================================================

/**
 * Navigate to an admin tab while preserving the proxy prefix in the URL.
 *
 * Derives the admin base path from window.location.pathname rather than
 * window.ROOT_PATH, so that proxy-embedded deployments (where ASGI
 * root_path is not forwarded and ROOT_PATH is empty) still navigate to
 * the correct proxy-scoped URL.
 *
 * @param {string} fragment - Hash fragment without '#' (e.g. "tools", "catalog").
 * @param {URLSearchParams} [searchParams] - Query params to include (team_id, include_inactive, etc.).
 */
export const navigateAdmin = function (fragment, searchParams) {
  const currentPath = window.location.pathname;
  // Find /admin in current path and use everything before it as the base.
  // e.g. /api/proxy/mcp/admin → base is /api/proxy/mcp
  // Use lastIndexOf so that path segments like /administrator don't match.
  const adminIdx = currentPath.lastIndexOf("/admin");
  const base =
    adminIdx >= 0
      ? window.location.origin + currentPath.slice(0, adminIdx)
      : window.ROOT_PATH || window.location.origin;
  // Preserve namespaced pagination state (*_page, *_size, *_inactive, *_q, *_tags)
  // from the current URL so that editing an item on page 3 returns to page 3.
  if (!searchParams) {
    searchParams = new URLSearchParams();
  }
  const currentUrlParams = new URLSearchParams(window.location.search);
  currentUrlParams.forEach((value, key) => {
    const isPaginationParam =
      key.endsWith("_page") ||
      key.endsWith("_size") ||
      (key.endsWith("_inactive") && key !== "include_inactive") ||
      key.endsWith("_q") ||
      key.endsWith("_tags");
    if (isPaginationParam && !searchParams.has(key)) {
      searchParams.set(key, value);
    }
  });

  const qs = searchParams.toString();
  const target = `${base}/admin${qs ? `?${qs}` : ""}#${fragment}`;

  // When the target URL is identical to the current URL (same path, query,
  // AND hash), browsers treat the assignment as an in-page anchor scroll
  // and skip the network reload.  This happens in proxy/iframe deployments
  // where the URL has no trailing slash (unlike direct mode where FastAPI
  // redirects /admin → /admin/, creating a path difference).  Force a full
  // reload so the UI always reflects the latest server state.
  // Fixes #3351 (root cause of #3324).
  if (window.location.href === target) {
    window.location.reload();
  } else {
    window.location.href = target;
  }
};
