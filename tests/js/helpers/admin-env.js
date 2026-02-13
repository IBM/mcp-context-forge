/**
 * Shared JSDOM + Istanbul instrumentation helper for admin.js tests.
 *
 * Usage in test files:
 *   import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";
 *   let win;
 *   beforeAll(() => { win = loadAdminJs(); });
 *   afterAll(() => { cleanupAdminJs(); });
 */

import { createInstrumenter } from "istanbul-lib-instrument";
import fs from "fs";
import path from "path";
import { JSDOM } from "jsdom";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const adminJsPath = path.resolve(
    __dirname,
    "../../../mcpgateway/static/admin.js",
);

let dom = null;
let instrumentedCode = null;

/**
 * Instrument admin.js once (cached) and execute it in a fresh JSDOM.
 * Returns the JSDOM window object with all admin.js globals available.
 *
 * NOTE: admin.js is a non-modular browser script that attaches functions
 * to the window object. JSDOM's runScripts + eval is the standard and
 * intended mechanism for loading such scripts in a test environment.
 * This is NOT evaluating untrusted input — the source is our own static asset.
 */
export function loadAdminJs() {
    if (!instrumentedCode) {
        const adminJsContent = fs.readFileSync(adminJsPath, "utf8");
        const instrumenter = createInstrumenter({
            compact: false,
            esModules: false,
            coverageVariable: "__coverage__",
        });
        instrumentedCode = instrumenter.instrumentSync(
            adminJsContent,
            adminJsPath,
        );
    }

    dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
        url: "http://localhost",
        runScripts: "outside-only",
    });

    // Suppress console noise from admin.js initialization
    dom.window.console = {
        ...dom.window.console,
        log: () => {},
        warn: () => {},
        error: () => {},
    };

    // Execute the instrumented script in JSDOM's sandbox — safe eval of our
    // own source file, required because admin.js is not an ES module.
    dom.window.eval(instrumentedCode); // eslint-disable-line no-eval
    return dom.window;
}

/**
 * Merge Istanbul counter objects: for each key, take the max of existing
 * and incoming values. This ensures coverage from multiple test files
 * accumulates rather than the last file overwriting all prior data.
 */
function mergeCounters(existing, incoming) {
    for (const key of Object.keys(incoming)) {
        if (typeof incoming[key] === "number") {
            existing[key] = (existing[key] || 0) + incoming[key];
        } else if (Array.isArray(incoming[key])) {
            // Branch counters are arrays of hit counts
            if (!existing[key]) {
                existing[key] = incoming[key].slice();
            } else {
                for (let i = 0; i < incoming[key].length; i++) {
                    existing[key][i] =
                        (existing[key][i] || 0) + (incoming[key][i] || 0);
                }
            }
        }
    }
}

/**
 * Bridge Istanbul coverage from JSDOM sandbox into Vitest's collector,
 * merging counters so that coverage accumulates across test files.
 * Then close the JSDOM window.
 */
export function cleanupAdminJs() {
    if (!dom) return;

    const jsCoverage = dom.window.__coverage__;
    if (jsCoverage && typeof jsCoverage === "object") {
        const target = "__VITEST_COVERAGE__";
        if (!globalThis[target]) {
            globalThis[target] = {};
        }
        for (const [filePath, fileCov] of Object.entries(jsCoverage)) {
            if (!globalThis[target][filePath]) {
                globalThis[target][filePath] = fileCov;
            } else {
                // Merge statement, function, and branch counters
                const existing = globalThis[target][filePath];
                mergeCounters(existing.s, fileCov.s);
                mergeCounters(existing.f, fileCov.f);
                mergeCounters(existing.b, fileCov.b);
            }
        }
    }

    dom.window.close();
    dom = null;
}
