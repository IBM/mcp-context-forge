/**
 * Bootstrap - Initialize window.Admin namespace FIRST before any modules load
 * This must be imported before any other modules
 */
window.Admin = window.Admin || {};


// ===================================================================
// MCPGATEWAY_ADMIN_DEBUG LOGGING CONTROL
// ===================================================================
window._originalConsoleLog = console.log;
window._originalConsoleDebug = console.debug;
try {
  if (window.localStorage.getItem("MCPGATEWAY_ADMIN_DEBUG") !== "1") {
    console.log = () => {};
    console.debug = () => {};
  }
} catch (_e) {
  console.log = () => {};
  console.debug = () => {};
}
