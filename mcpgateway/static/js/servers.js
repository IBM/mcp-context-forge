
import { safeGetElement } from "./utils";

// ===================================================================
// GLOBAL EXPORTS - Make functions available to HTML onclick handlers
// ===================================================================

/**
* Load servers (Virtual Servers / Catalog) with optional include_inactive parameter
*/
export const loadServers = async function () {
    const checkbox = safeGetElement("show-inactive-servers");
    const includeInactive = checkbox ? checkbox.checked : false;

    // Build URL with include_inactive parameter
    const url = new URL(window.location);
    if (includeInactive) {
        url.searchParams.set("include_inactive", "true");
    } else {
        url.searchParams.delete("include_inactive");
    }

    // Reload the page with the updated parameters
    // Since the catalog panel is server-side rendered, we need a full page reload
    window.location.href = url.toString();
}