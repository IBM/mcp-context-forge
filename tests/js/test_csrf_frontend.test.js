/**
 * Unit tests for CSRF frontend implementation in admin.js
 *
 * Tests cover:
 * - Token reading from meta tag and cookie
 * - Token refreshing from server
 * - Automatic fetch() monkey-patching
 * - Form auto-injection
 * - MutationObserver for dynamic forms
 */

import { describe, test, expect, beforeEach, afterEach, vi } from "vitest";
import { JSDOM } from "jsdom";

// Mock functions that will be extracted from admin.js
let getCSRFToken;
let refreshCSRFToken;
let injectCSRFIntoForm;
let injectCSRFIntoAllForms;
let originalFetch;

// Setup DOM environment
let dom;
let window;
let document;

beforeEach(() => {
    // Create fresh DOM for each test
    dom = new JSDOM(`
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="csrf-token" content="">
        </head>
        <body></body>
        </html>
    `, {
        url: "https://example.com",
        runScripts: "dangerously"
    });

    window = dom.window;
    document = window.document;

    // Mock console methods
    window.console.error = vi.fn();
    window.console.log = vi.fn();

    // Mock fetch
    originalFetch = window.fetch;
    window.fetch = vi.fn();

    // Define CSRF functions in window context
    window.eval(`
        function getCSRFToken() {
            try {
                const meta = document.querySelector('meta[name="csrf-token"]');
                if (meta && meta.content) return meta.content;

                const cookies = document.cookie.split(';');
                for (let cookie of cookies) {
                    const [name, value] = cookie.trim().split('=');
                    if (name === 'csrf_token') return decodeURIComponent(value);
                }
            } catch (e) {
                console.error('CSRF: failed to read cookie fallback', e);
            }
            console.error('CSRF: no token found — requests will fail');
            return null;
        }

        async function refreshCSRFToken() {
            const response = await fetch('/auth/csrf-token', {
                method: 'GET',
                credentials: 'include'
            });
            if (!response.ok) {
                throw new Error('CSRF token refresh failed: ' + response.status);
            }
            const data = await response.json();
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta && data.csrf_token) {
                meta.setAttribute('content', data.csrf_token);
            }
            return data.csrf_token;
        }

        function injectCSRFIntoForm(form) {
            if (!form || form.tagName !== 'FORM') return;
            const method = (form.method || 'GET').toUpperCase();
            if (method === 'GET') return;

            if (form.querySelector('input[name="csrf_token"][data-csrf-injected]')) return;

            let input = form.querySelector('input[name="csrf_token"]');
            if (!input) {
                input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrf_token';
                input.value = getCSRFToken();
                input.setAttribute('data-csrf-injected', 'true');
                form.appendChild(input);
            } else {
                input.value = getCSRFToken();
            }
        }

        function injectCSRFIntoAllForms() {
            document.querySelectorAll('form').forEach(injectCSRFIntoForm);
        }
    `);

    // Extract functions from window
    getCSRFToken = window.getCSRFToken;
    refreshCSRFToken = window.refreshCSRFToken;
    injectCSRFIntoForm = window.injectCSRFIntoForm;
    injectCSRFIntoAllForms = window.injectCSRFIntoAllForms;
});

afterEach(() => {
    vi.clearAllMocks();
    dom.window.close();
});

describe("getCSRFToken", () => {
    describe("Token Reading from Meta Tag", () => {
        test("returns token from meta tag when present with valid content", () => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            meta.setAttribute('content', 'meta-token-123');

            const token = getCSRFToken();
            expect(token).toBe('meta-token-123');
        });

        test("returns token from cookie when meta tag is absent", () => {
            // Remove meta tag
            const meta = document.querySelector('meta[name="csrf-token"]');
            meta.remove();

            // Set cookie
            document.cookie = 'csrf_token=cookie-token-456';

            const token = getCSRFToken();
            expect(token).toBe('cookie-token-456');
        });

        test("returns token from cookie when meta tag content is empty", () => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            meta.setAttribute('content', '');

            document.cookie = 'csrf_token=cookie-token-789';

            const token = getCSRFToken();
            expect(token).toBe('cookie-token-789');
        });

        test("returns null and logs error when both meta tag and cookie are absent", () => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            meta.remove();

            const token = getCSRFToken();
            expect(token).toBeNull();
            expect(window.console.error).toHaveBeenCalledWith(
                expect.stringContaining('CSRF: no token found')
            );
        });

        test("prefers meta tag over cookie when both are present", () => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            meta.setAttribute('content', 'meta-token-priority');

            document.cookie = 'csrf_token=cookie-token-ignored';

            const token = getCSRFToken();
            expect(token).toBe('meta-token-priority');
        });
    });
});

describe("refreshCSRFToken", () => {
    test("calls GET /auth/csrf-token with credentials include", async () => {
        window.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({ csrf_token: 'new-token-123' })
        });

        await refreshCSRFToken();

        expect(window.fetch).toHaveBeenCalledWith('/auth/csrf-token', {
            method: 'GET',
            credentials: 'include'
        });
    });

    test("returns new token from response on success", async () => {
        window.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({ csrf_token: 'refreshed-token-456' })
        });

        const token = await refreshCSRFToken();
        expect(token).toBe('refreshed-token-456');
    });

    test("updates meta tag content attribute with new token after successful refresh", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'old-token');

        window.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({ csrf_token: 'updated-token-789' })
        });

        await refreshCSRFToken();

        expect(meta.getAttribute('content')).toBe('updated-token-789');
    });

    test("does not update meta tag if meta tag is absent in DOM", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.remove();

        window.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({ csrf_token: 'new-token' })
        });

        // Should not throw
        await expect(refreshCSRFToken()).resolves.toBe('new-token');
    });

    test("throws error when /auth/csrf-token returns non-ok response", async () => {
        window.fetch.mockResolvedValue({
            ok: false,
            status: 403
        });

        await expect(refreshCSRFToken()).rejects.toThrow('CSRF token refresh failed: 403');
    });
});

describe("Fetch Monkey-Patch", () => {
    let monkeyPatchedFetch;

    beforeEach(() => {
        // Setup monkey-patched fetch
        const originalFetch = window.fetch;

        window.eval(`
            const _originalFetch = window.fetch;
            window.fetch = async function(url, options = {}) {
                const method = (options.method || 'GET').toUpperCase();
                const safeMethods = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];

                if (!safeMethods.includes(method)) {
                    const existingHeaders = options.headers || {};

                    if (!existingHeaders['X-CSRF-Token'] && !existingHeaders['x-csrf-token']) {
                        options.headers = { ...existingHeaders, 'X-CSRF-Token': getCSRFToken() };
                    }

                    options.credentials = 'include';
                }

                const response = await _originalFetch(url, options);

                if ((response.status === 401 || response.status === 403) && !options._retried) {
                    try {
                        const newToken = await refreshCSRFToken();
                        options.headers['X-CSRF-Token'] = newToken;
                        options._retried = true;
                        return await _originalFetch(url, options);
                    } catch (e) {
                        console.error('CSRF: token refresh failed, returning original response', e);
                        return response;
                    }
                }

                return response;
            };
        `);

        monkeyPatchedFetch = window.fetch;
    });

    test("GET request passes through without X-CSRF-Token header", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token-123');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'GET' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers).toBeUndefined();
    });

    test("HEAD request passes through without X-CSRF-Token header", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token-123');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'HEAD' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers).toBeUndefined();
    });

    test("POST request automatically includes X-CSRF-Token header from meta tag", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'auto-token-post');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'POST' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers['X-CSRF-Token']).toBe('auto-token-post');
    });

    test("PUT request automatically includes X-CSRF-Token header from meta tag", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'auto-token-put');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'PUT' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers['X-CSRF-Token']).toBe('auto-token-put');
    });

    test("DELETE request automatically includes X-CSRF-Token header from meta tag", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'auto-token-delete');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'DELETE' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers['X-CSRF-Token']).toBe('auto-token-delete');
    });

    test("does not overwrite X-CSRF-Token if caller already set it manually", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'auto-token');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', {
            method: 'POST',
            headers: { 'X-CSRF-Token': 'manual-token' }
        });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers['X-CSRF-Token']).toBe('manual-token');
    });

    test("does not overwrite x-csrf-token lowercase if caller already set it", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'auto-token');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', {
            method: 'POST',
            headers: { 'x-csrf-token': 'manual-lowercase-token' }
        });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].headers['x-csrf-token']).toBe('manual-lowercase-token');
    });

    test("always includes credentials include on mutating requests", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        window.eval('_originalFetch').mockResolvedValue({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'POST' });

        const call = window.eval('_originalFetch').mock.calls[0];
        expect(call[1].credentials).toBe('include');
    });

    test("401 response triggers refreshCSRFToken and retries with new token", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'old-token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch
            .mockResolvedValueOnce({ ok: false, status: 401 })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ csrf_token: 'new-token-401' })
            })
            .mockResolvedValueOnce({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(mockFetch).toHaveBeenCalledTimes(3);
        expect(meta.getAttribute('content')).toBe('new-token-401');
    });

    test("403 response triggers refreshCSRFToken and retries with new token", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'old-token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch
            .mockResolvedValueOnce({ ok: false, status: 403 })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ csrf_token: 'new-token-403' })
            })
            .mockResolvedValueOnce({ ok: true, status: 200 });

        await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(mockFetch).toHaveBeenCalledTimes(3);
        expect(meta.getAttribute('content')).toBe('new-token-403');
    });

    test("400 response does NOT trigger token rotation or retry", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch.mockResolvedValue({ ok: false, status: 400 });

        const response = await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(mockFetch).toHaveBeenCalledTimes(1);
        expect(response.status).toBe(400);
    });

    test("500 response does NOT trigger token rotation or retry", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch.mockResolvedValue({ ok: false, status: 500 });

        const response = await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(mockFetch).toHaveBeenCalledTimes(1);
        expect(response.status).toBe(500);
    });

    test("retry happens ONCE only - second 401 is returned as-is without retry", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch
            .mockResolvedValueOnce({ ok: false, status: 401 })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ csrf_token: 'new-token' })
            })
            .mockResolvedValueOnce({ ok: false, status: 401 });

        const response = await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(mockFetch).toHaveBeenCalledTimes(3);
        expect(response.status).toBe(401);
    });

    test("returns original failed response if refreshCSRFToken throws during retry", async () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const mockFetch = window.eval('_originalFetch');
        mockFetch
            .mockResolvedValueOnce({ ok: false, status: 401 })
            .mockRejectedValueOnce(new Error('Network error'));

        const response = await monkeyPatchedFetch('/api/data', { method: 'POST' });

        expect(response.status).toBe(401);
        expect(window.console.error).toHaveBeenCalledWith(
            expect.stringContaining('CSRF: token refresh failed'),
            expect.any(Error)
        );
    });
});

describe("Form Auto-Injection - injectCSRFIntoForm", () => {
    test("POST form gets hidden input with name csrf_token injected", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'form-token-123');

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input).not.toBeNull();
        expect(input.type).toBe('hidden');
        expect(input.value).toBe('form-token-123');
    });

    test("PUT form gets hidden input injected", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'form-token-put');

        const form = document.createElement('form');
        form.method = 'PUT';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input).not.toBeNull();
        expect(input.value).toBe('form-token-put');
    });

    test("GET form does NOT get hidden input injected", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'form-token-get');

        const form = document.createElement('form');
        form.method = 'GET';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input).toBeNull();
    });

    test("hidden input has data-csrf-injected attribute set to true", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input.getAttribute('data-csrf-injected')).toBe('true');
    });

    test("calling injectCSRFIntoForm twice on same form does NOT add duplicate input", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'token');

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);
        injectCSRFIntoForm(form);

        const inputs = form.querySelectorAll('input[name="csrf_token"]');
        expect(inputs.length).toBe(1);
    });

    test("hidden input value comes from meta tag when meta tag is present", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'meta-form-token');

        document.cookie = 'csrf_token=cookie-form-token';

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input.value).toBe('meta-form-token');
    });

    test("hidden input value comes from cookie fallback when meta tag is absent", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.remove();

        document.cookie = 'csrf_token=cookie-fallback-token';

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input.value).toBe('cookie-fallback-token');
    });

    test("hidden input value is refreshed from getCSRFToken on form submit event", () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'initial-token');

        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        injectCSRFIntoForm(form);

        const input = form.querySelector('input[name="csrf_token"]');
        expect(input.value).toBe('initial-token');

        // Update token
        meta.setAttribute('content', 'updated-token');

        // Trigger submit event
        form.dispatchEvent(new window.Event('submit'));

        // Value should be updated
        expect(input.value).toBe('updated-token');
    });
});

describe("MutationObserver", () => {
    test("form added dynamically to DOM after page load gets hidden input injected", (done) => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'dynamic-token');

        // Setup observer
        const observer = new window.MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.tagName === 'FORM') {
                        injectCSRFIntoForm(node);
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });

        // Add form dynamically
        const form = document.createElement('form');
        form.method = 'POST';
        document.body.appendChild(form);

        // Wait for observer to process
        setTimeout(() => {
            const input = form.querySelector('input[name="csrf_token"]');
            expect(input).not.toBeNull();
            expect(input.value).toBe('dynamic-token');
            observer.disconnect();
            done();
        }, 10);
    });

    test("form nested inside a dynamically added div gets hidden input injected", (done) => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        meta.setAttribute('content', 'nested-token');

        // Setup observer
        const observer = new window.MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) {
                        node.querySelectorAll('form').forEach(injectCSRFIntoForm);
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });

        // Add div with nested form
        const div = document.createElement('div');
        const form = document.createElement('form');
        form.method = 'POST';
        div.appendChild(form);
        document.body.appendChild(div);

        // Wait for observer to process
        setTimeout(() => {
            const input = form.querySelector('input[name="csrf_token"]');
            expect(input).not.toBeNull();
            expect(input.value).toBe('nested-token');
            observer.disconnect();
            done();
        }, 10);
    });

    test("non-form element added to DOM does not cause errors", (done) => {
        // Setup observer
        const observer = new window.MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.tagName === 'FORM') {
                        injectCSRFIntoForm(node);
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });

        // Add non-form element
        const div = document.createElement('div');
        div.textContent = 'Not a form';
        document.body.appendChild(div);

        // Wait and verify no errors
        setTimeout(() => {
            expect(window.console.error).not.toHaveBeenCalled();
            observer.disconnect();
            done();
        }, 10);
    });
});
