/**
 * Minimal JSDOM environment for DOM-dependent tests.
 * Only use this when testing actual DOM manipulation.
 */

import { JSDOM } from "jsdom";

/**
 * Create a minimal JSDOM environment for DOM-dependent tests.
 * @returns {Object} Environment with window, document, and cleanup function
 */
export function createDOMEnvironment() {
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    url: "http://localhost",
    runScripts: "outside-only",
  });

  // Suppress console noise during tests
  dom.window.console = {
    ...dom.window.console,
    log: () => {},
    warn: () => {},
    error: () => {},
  };

  return {
    window: dom.window,
    document: dom.window.document,
    cleanup: () => dom.window.close(),
  };
}
