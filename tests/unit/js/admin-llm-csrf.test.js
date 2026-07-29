/**
 * Regression tests for #5739 — LLM Settings write requests failing CSRF
 * validation because llmModels.js never attached X-CSRF-Token.
 *
 * These tests exercise the shared `llmRequestHeaders()` helper (indirectly,
 * through the exported write functions and the `llmApiInfoApp().runTest`
 * Alpine method) and assert that:
 *   - `X-CSRF-Token` is attached from the `mcpgateway_csrf_token` cookie on
 *     every state-changing request.
 *   - `Authorization` is OMITTED when `getAuthToken()` resolves to "" (the
 *     httponly session-cookie case) — regression guard for the empty-Bearer
 *     bug.
 *   - `Authorization: Bearer <token>` IS present when a real bearer token is
 *     available.
 *
 * Direct coverage (one representative function per HTTP verb, plus the
 * Alpine `runTest` method):
 *   - saveLLMProvider      -> POST /llm/providers   and PATCH /llm/providers/{id}
 *   - saveLLMModel         -> POST /llm/models
 *   - deleteLLMProvider    -> DELETE /llm/providers/{id}
 *   - deleteLLMModel       -> DELETE /llm/models/{id}
 *   - toggleLLMProvider    -> POST /llm/providers/{id}/state
 *   - fetchLLMProviderModels -> POST /admin/llm/providers/{id}/fetch-models (no body)
 *   - checkLLMProviderHealth -> POST /admin/llm/providers/{id}/health (no body)
 *   - llmApiInfoApp().runTest -> POST /admin/llm/test (Alpine component method)
 *
 * The "missing CSRF cookie" block below additionally covers all remaining
 * write sites that go through the same `llmRequestHeaders()` helper --
 * syncLLMProviderModels, fetchModelsForModelModal, toggleLLMModel -- so all
 * 11 write call sites are exercised for the no-cookie regression, not just
 * the 8 above. Those three are also exercised for behavior (not CSRF
 * headers) in llmModels.test.js.
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  saveLLMProvider,
  deleteLLMProvider,
  toggleLLMProvider,
  fetchLLMProviderModels,
  checkLLMProviderHealth,
  saveLLMModel,
  deleteLLMModel,
  llmApiInfoApp,
  syncLLMProviderModels,
  fetchModelsForModelModal,
  toggleLLMModel,
} from "../../../mcpgateway/admin_ui/llmModels.js";

vi.mock("../../../mcpgateway/admin_ui/modals.js", () => ({
  showCopyableModal: vi.fn(),
}));

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
  parseErrorResponse: vi.fn((response, defaultMsg) =>
    Promise.resolve(defaultMsg)
  ),
}));

// getAuthToken defaults to "" (httponly session-cookie login) for most tests;
// individual tests override this to prove the Authorization-present case.
const getAuthTokenMock = vi.fn(() => Promise.resolve(""));
vi.mock("../../../mcpgateway/admin_ui/tokens.js", () => ({
  getAuthToken: (...args) => getAuthTokenMock(...args),
}));

// utils.js is intentionally NOT mocked for getCookie/safeGetElement — we want
// the real cookie-reading implementation exercised against jsdom's
// document.cookie, since that is the exact mechanism the fix relies on.

const CSRF_COOKIE_VALUE = "test-csrf-value";

function setCsrfCookie(value = CSRF_COOKIE_VALUE) {
  document.cookie = `mcpgateway_csrf_token=${value}`;
}

function clearCookies() {
  // jsdom does not support wildcard cookie clearing; expire the one we set.
  document.cookie =
    "mcpgateway_csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function setupProviderFormDOM() {
  const ids = [
    "llm-provider-id",
    "llm-provider-name",
    "llm-provider-description",
    "llm-provider-api-key",
    "llm-provider-api-base",
    "llm-provider-default-model",
    "llm-provider-temperature",
    "llm-provider-max-tokens",
  ];
  const els = {};
  for (const id of ids) {
    const el = document.createElement("input");
    el.id = id;
    document.body.appendChild(el);
    els[id] = el;
  }
  els["llm-provider-temperature"].value = "0.7";

  const providerType = document.createElement("select");
  providerType.id = "llm-provider-type";
  providerType.value = "openai";
  document.body.appendChild(providerType);

  const enabled = document.createElement("input");
  enabled.id = "llm-provider-enabled";
  enabled.type = "checkbox";
  document.body.appendChild(enabled);

  const configFields = document.createElement("div");
  configFields.id = "llm-provider-config-fields";
  document.body.appendChild(configFields);

  const modal = document.createElement("div");
  modal.id = "llm-provider-modal";
  document.body.appendChild(modal);

  const container = document.createElement("div");
  container.id = "llm-providers-container";
  document.body.appendChild(container);

  return els;
}

function setupModelFormDOM() {
  const ids = [
    "llm-model-id",
    "llm-model-model-id",
    "llm-model-name",
    "llm-model-alias",
    "llm-model-description",
    "llm-model-context-window",
    "llm-model-max-output",
  ];
  const els = {};
  for (const id of ids) {
    const el = document.createElement("input");
    el.id = id;
    document.body.appendChild(el);
    els[id] = el;
  }
  els["llm-model-name"].value = "GPT-4";
  els["llm-model-model-id"].value = "gpt-4";

  const providerSelect = document.createElement("select");
  providerSelect.id = "llm-model-provider";
  providerSelect.value = "p1";
  document.body.appendChild(providerSelect);

  for (const id of [
    "llm-model-supports-chat",
    "llm-model-supports-streaming",
    "llm-model-supports-functions",
    "llm-model-supports-vision",
    "llm-model-enabled",
    "llm-model-deprecated",
  ]) {
    const cb = document.createElement("input");
    cb.id = id;
    cb.type = "checkbox";
    document.body.appendChild(cb);
  }

  const modal = document.createElement("div");
  modal.id = "llm-model-modal";
  document.body.appendChild(modal);

  const container = document.createElement("div");
  container.id = "llm-models-container";
  document.body.appendChild(container);

  return els;
}

beforeEach(() => {
  window.ROOT_PATH = "";
  window.htmx = {
    trigger: vi.fn(),
    ajax: vi.fn(),
    process: vi.fn(),
  };
  getAuthTokenMock.mockReset();
  getAuthTokenMock.mockResolvedValue("");
  setCsrfCookie();
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  delete window.htmx;
  clearCookies();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// saveLLMProvider — POST (create) and PATCH (update)
// ---------------------------------------------------------------------------
describe("saveLLMProvider CSRF headers", () => {
  test("POST /llm/providers includes X-CSRF-Token and omits Authorization", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "new-provider" }),
    });
    setupProviderFormDOM();

    await saveLLMProvider({ preventDefault: vi.fn() });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
  });

  test("PATCH /llm/providers/{id} includes X-CSRF-Token", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    });
    const els = setupProviderFormDOM();
    els["llm-provider-id"].value = "provider-1";

    await saveLLMProvider({ preventDefault: vi.fn() });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
  });

  test("attaches Authorization when a real bearer token is available", async () => {
    getAuthTokenMock.mockResolvedValue("real-bearer-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "new-provider" }),
    });
    setupProviderFormDOM();

    await saveLLMProvider({ preventDefault: vi.fn() });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer real-bearer-token",
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
  });
});

// ---------------------------------------------------------------------------
// deleteLLMProvider — DELETE
// ---------------------------------------------------------------------------
describe("deleteLLMProvider CSRF headers", () => {
  test("DELETE includes X-CSRF-Token and omits Authorization", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });
    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await deleteLLMProvider("provider-1", "Test Provider");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");

    confirmSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// toggleLLMProvider — POST state-toggle, no body
// ---------------------------------------------------------------------------
describe("toggleLLMProvider CSRF headers", () => {
  test("POST /state includes X-CSRF-Token and omits Content-Type/Authorization", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });
    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await toggleLLMProvider("provider-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/providers/provider-1/state",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
    expect(options.headers).not.toHaveProperty("Content-Type");
  });
});

// ---------------------------------------------------------------------------
// fetchLLMProviderModels — POST /admin/llm/*, no body (enforce_admin_csrf)
// ---------------------------------------------------------------------------
describe("fetchLLMProviderModels CSRF headers", () => {
  test("POST fetch-models includes X-CSRF-Token", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ success: true, count: 0, models: [] }),
    });

    await fetchLLMProviderModels("provider-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/llm/providers/provider-1/fetch-models",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
  });
});

// ---------------------------------------------------------------------------
// checkLLMProviderHealth — POST /admin/llm/*, no body (enforce_admin_csrf)
// ---------------------------------------------------------------------------
describe("checkLLMProviderHealth CSRF headers", () => {
  test("POST health includes X-CSRF-Token", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "healthy", latency_ms: 5 }),
    });
    const container = document.createElement("div");
    container.id = "llm-providers-container";
    document.body.appendChild(container);

    await checkLLMProviderHealth("provider-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/llm/providers/provider-1/health",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
  });
});

// ---------------------------------------------------------------------------
// saveLLMModel — POST (create)
// ---------------------------------------------------------------------------
describe("saveLLMModel CSRF headers", () => {
  test("POST /llm/models includes X-CSRF-Token and omits Authorization", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "new-model" }),
    });
    setupModelFormDOM();

    await saveLLMModel({ preventDefault: vi.fn() });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/models",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
  });
});

// ---------------------------------------------------------------------------
// deleteLLMModel — DELETE
// ---------------------------------------------------------------------------
describe("deleteLLMModel CSRF headers", () => {
  test("DELETE includes X-CSRF-Token and omits Authorization", async () => {
    const confirmSpy = vi.spyOn(globalThis, "confirm").mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
    });
    const container = document.createElement("div");
    container.id = "llm-models-container";
    document.body.appendChild(container);

    await deleteLLMModel("model-1", "GPT-4");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/llm/models/model-1",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");

    confirmSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// llmApiInfoApp().runTest — Alpine component method, POST /admin/llm/test
// ---------------------------------------------------------------------------
describe("llmApiInfoApp().runTest CSRF headers", () => {
  test("POST /admin/llm/test includes X-CSRF-Token and omits Authorization", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: () =>
        Promise.resolve({
          success: true,
          metrics: { modelCount: 1 },
          data: { data: [{ id: "gpt-4" }] },
        }),
    });

    const app = llmApiInfoApp();
    app.testType = "models";
    await app.runTest();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/llm/test",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
          "Content-Type": "application/json",
        }),
      })
    );
    const [, options] = fetchSpy.mock.calls[0];
    expect(options.headers).not.toHaveProperty("Authorization");
    expect(app.testSuccess).toBe(true);
  });

  test("attaches Authorization when a real bearer token is available", async () => {
    getAuthTokenMock.mockResolvedValue("real-bearer-token");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: () =>
        Promise.resolve({ success: true, metrics: {}, data: { data: [] } }),
    });

    const app = llmApiInfoApp();
    app.testType = "models";
    await app.runTest();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/admin/llm/test",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer real-bearer-token",
          "X-CSRF-Token": CSRF_COOKIE_VALUE,
        }),
      })
    );
  });
});

// ---------------------------------------------------------------------------
// No CSRF cookie present — X-CSRF-Token must be omitted, not sent empty
//
// Table-driven over all 11 write call sites in llmModels.js so a future
// write site only needs one new row here.
// ---------------------------------------------------------------------------
describe("missing CSRF cookie", () => {
  const cases = [
    [
      "saveLLMProvider (POST /llm/providers)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ id: "new-provider" }),
        });
        setupProviderFormDOM();
        await saveLLMProvider({ preventDefault: vi.fn() });
        return fetchSpy;
      },
    ],
    [
      "saveLLMModel (POST /llm/models)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ id: "new-model" }),
        });
        setupModelFormDOM();
        await saveLLMModel({ preventDefault: vi.fn() });
        return fetchSpy;
      },
    ],
    [
      "deleteLLMProvider (DELETE /llm/providers/{id})",
      async () => {
        vi.spyOn(globalThis, "confirm").mockReturnValue(true);
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
        });
        const container = document.createElement("div");
        container.id = "llm-providers-container";
        document.body.appendChild(container);
        await deleteLLMProvider("provider-1", "Test Provider");
        return fetchSpy;
      },
    ],
    [
      "deleteLLMModel (DELETE /llm/models/{id})",
      async () => {
        vi.spyOn(globalThis, "confirm").mockReturnValue(true);
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
        });
        const container = document.createElement("div");
        container.id = "llm-models-container";
        document.body.appendChild(container);
        await deleteLLMModel("model-1", "GPT-4");
        return fetchSpy;
      },
    ],
    [
      "toggleLLMProvider (POST /llm/providers/{id}/state)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
        });
        const container = document.createElement("div");
        container.id = "llm-providers-container";
        document.body.appendChild(container);
        await toggleLLMProvider("provider-1");
        return fetchSpy;
      },
    ],
    [
      "toggleLLMModel (POST /llm/models/{id}/state)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
        });
        const container = document.createElement("div");
        container.id = "llm-models-container";
        document.body.appendChild(container);
        await toggleLLMModel("model-1");
        return fetchSpy;
      },
    ],
    [
      "fetchLLMProviderModels (POST /admin/llm/providers/{id}/fetch-models)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () =>
            Promise.resolve({ success: true, count: 0, models: [] }),
        });
        await fetchLLMProviderModels("provider-1");
        return fetchSpy;
      },
    ],
    [
      "checkLLMProviderHealth (POST /admin/llm/providers/{id}/health)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () =>
            Promise.resolve({ status: "healthy", latency_ms: 5 }),
        });
        const container = document.createElement("div");
        container.id = "llm-providers-container";
        document.body.appendChild(container);
        await checkLLMProviderHealth("provider-1");
        return fetchSpy;
      },
    ],
    [
      "syncLLMProviderModels (POST /admin/llm/providers/{id}/sync-models)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              message: "Synced 5 models",
              total: 10,
            }),
        });
        const container = document.createElement("div");
        container.id = "llm-models-container";
        document.body.appendChild(container);
        await syncLLMProviderModels("provider-1");
        return fetchSpy;
      },
    ],
    [
      "fetchModelsForModelModal (POST /admin/llm/providers/{id}/fetch-models)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              models: [{ id: "gpt-4", name: "GPT-4" }],
            }),
        });
        const providerSelect = document.createElement("select");
        providerSelect.id = "llm-model-provider";
        const option = document.createElement("option");
        option.value = "p1";
        option.selected = true;
        providerSelect.appendChild(option);
        document.body.appendChild(providerSelect);

        const statusEl = document.createElement("div");
        statusEl.id = "llm-model-fetch-status";
        statusEl.classList.add("hidden");
        document.body.appendChild(statusEl);

        await fetchModelsForModelModal();
        return fetchSpy;
      },
    ],
    [
      "llmApiInfoApp().runTest (POST /admin/llm/test)",
      async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
          ok: true,
          status: 200,
          statusText: "OK",
          json: () =>
            Promise.resolve({
              success: true,
              metrics: { modelCount: 1 },
              data: { data: [{ id: "gpt-4" }] },
            }),
        });
        const app = llmApiInfoApp();
        app.testType = "models";
        await app.runTest();
        return fetchSpy;
      },
    ],
  ];

  test.each(cases)(
    "%s omits X-CSRF-Token when no cookie is set",
    async (_name, invoke) => {
      clearCookies();

      const fetchSpy = await invoke();

      const [, options] = fetchSpy.mock.calls[0];
      expect(options.headers).not.toHaveProperty("X-CSRF-Token");
    }
  );
});
