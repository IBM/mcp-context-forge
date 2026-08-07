// Location: ./client/server/test/auth.test.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from "vitest";

import { config } from "../src/config.js";
import { buildTestApp, type TestApp } from "./helpers/build-app.js";

function mockUpstreamLogin(ok: boolean, body: unknown, status = ok ? 200 : 401): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    })),
  );
}

async function login(app: TestApp): Promise<{ cookies: string[]; csrfToken: string }> {
  mockUpstreamLogin(true, {
    access_token: "upstream-jwt", // pragma: allowlist secret
    user: { email: "user@example.com", is_admin: false },
  });

  const response = await app.fastify.inject({
    method: "POST",
    url: "/auth/login",
    payload: { email: "user@example.com", password: "secret" }, // pragma: allowlist secret
  });

  expect(response.statusCode).toBe(200);
  const cookies = response.cookies.map((c) => `${c.name}=${c.value}`);
  const csrfToken = response.json().csrfToken as string;
  expect(csrfToken).toBeTruthy();
  return { cookies, csrfToken };
}

describe("POST /auth/login", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never returns the upstream access_token to the browser", async () => {
    const app = await buildTestApp();
    mockUpstreamLogin(true, {
      access_token: "upstream-jwt", // pragma: allowlist secret
      user: { email: "user@example.com", is_admin: false },
    });

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/login",
      payload: { email: "user@example.com", password: "secret" }, // pragma: allowlist secret
    });

    expect(response.statusCode).toBe(200);
    expect(JSON.stringify(response.json())).not.toContain("upstream-jwt");
    const setCookieNames = response.cookies.map((c) => c.name);
    expect(setCookieNames).toContain("bff_sid");
    expect(setCookieNames).toContain("bff_csrf");
  });

  it("sets the session cookie's maxAge to the upstream token's own expires_in, not a fixed BFF default", async () => {
    const app = await buildTestApp();
    mockUpstreamLogin(true, {
      access_token: "upstream-jwt", // pragma: allowlist secret
      expires_in: 1200, // 20 minutes — FastAPI's default TOKEN_EXPIRY
      user: { email: "user@example.com", is_admin: false },
    });

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/login",
      payload: { email: "user@example.com", password: "secret" }, // pragma: allowlist secret
    });

    const sessionCookie = response.cookies.find((c) => c.name === "bff_sid");
    expect(sessionCookie?.maxAge).toBe(1200);
  });

  it("falls back to the BFF's default TTL if the upstream response omits expires_in", async () => {
    const app = await buildTestApp();
    mockUpstreamLogin(true, {
      access_token: "upstream-jwt", // pragma: allowlist secret
      user: { email: "user@example.com", is_admin: false },
    });

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/login",
      payload: { email: "user@example.com", password: "secret" }, // pragma: allowlist secret
    });

    const sessionCookie = response.cookies.find((c) => c.name === "bff_sid");
    expect(sessionCookie?.maxAge).toBeGreaterThan(1200); // sanity: not accidentally near-zero
  });

  it("passes through upstream failure status without leaking a session", async () => {
    const app = await buildTestApp();
    mockUpstreamLogin(false, { detail: "Invalid email or password" }, 401);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/login",
      payload: { email: "user@example.com", password: "wrong" }, // pragma: allowlist secret
    });

    expect(response.statusCode).toBe(401);
    expect(response.cookies.map((c) => c.name)).not.toContain("bff_sid");
  });

  it("rejects a request missing credentials before calling upstream", async () => {
    const app = await buildTestApp();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/login",
      payload: { email: "a@b.com" },
    });

    expect(response.statusCode).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("GET /auth/session", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reports unauthenticated with no error for an anonymous visitor", async () => {
    const app = await buildTestApp();
    const response = await app.fastify.inject({ method: "GET", url: "/auth/session" });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual({ authenticated: false });
  });

  it("reports the session user and a fresh csrfToken once logged in", async () => {
    const app = await buildTestApp();
    const { cookies } = await login(app);

    const response = await app.fastify.inject({
      method: "GET",
      url: "/auth/session",
      headers: { cookie: cookies.join("; ") },
    });

    const payload = response.json();
    expect(payload.authenticated).toBe(true);
    expect(payload.user.email).toBe("user@example.com");
    expect(payload.csrfToken).toBeTruthy();
  });
});

describe("POST /auth/logout", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("rejects without a valid CSRF token", async () => {
    const app = await buildTestApp();
    const { cookies } = await login(app);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/logout",
      headers: { cookie: cookies.join("; ") }, // no X-CSRF-Token
    });

    expect(response.statusCode).toBe(403);
  });

  it("clears cookies and drops the Redis session given a valid CSRF token", async () => {
    const app = await buildTestApp();
    const { cookies, csrfToken } = await login(app);

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/logout",
      headers: { cookie: cookies.join("; "), "x-csrf-token": csrfToken },
    });

    expect(response.statusCode).toBe(200);
    const cleared = response.cookies.find((c) => c.name === "bff_sid");
    expect(cleared?.value).toBe("");

    // Session is really gone, not just the cookie cleared client-side.
    const followUp = await app.fastify.inject({
      method: "GET",
      url: "/auth/session",
      headers: { cookie: cookies.join("; ") },
    });
    expect(followUp.json()).toEqual({ authenticated: false });
  });

  it("is safe to call twice (idempotent) given a still-valid CSRF pair", async () => {
    const app = await buildTestApp();
    const { cookies, csrfToken } = await login(app);
    const headers = { cookie: cookies.join("; "), "x-csrf-token": csrfToken };

    const first = await app.fastify.inject({ method: "POST", url: "/auth/logout", headers });
    const second = await app.fastify.inject({ method: "POST", url: "/auth/logout", headers });

    expect(first.statusCode).toBe(200);
    expect(second.statusCode).toBe(200);
  });

  it("revokes the upstream JWT via FastAPI's bearer-token logout, not just the BFF session", async () => {
    const app = await buildTestApp();
    const { cookies, csrfToken } = await login(app);

    const fetchCalls: Array<{ url: string; authorization: string | undefined }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const headers = init?.headers as Record<string, string> | undefined;
        fetchCalls.push({ url: String(url), authorization: headers?.authorization });
        return { ok: true, status: 200, json: async () => ({}), text: async () => "" };
      }),
    );

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/logout",
      headers: { cookie: cookies.join("; "), "x-csrf-token": csrfToken },
    });

    expect(response.statusCode).toBe(200);
    const revokeCall = fetchCalls.find((call) => call.url === `${config.fastapiUrl}/auth/logout`);
    expect(revokeCall).toBeTruthy();
    // The stored bearer token, minted at login — never a session/cookie value.
    expect(revokeCall?.authorization).toBe("Bearer upstream-jwt");
  });

  it("still clears the BFF session even when upstream token revocation fails", async () => {
    const app = await buildTestApp();
    const { cookies, csrfToken } = await login(app);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("upstream unreachable");
      }),
    );

    const response = await app.fastify.inject({
      method: "POST",
      url: "/auth/logout",
      headers: { cookie: cookies.join("; "), "x-csrf-token": csrfToken },
    });

    expect(response.statusCode).toBe(200);
    const cleared = response.cookies.find((c) => c.name === "bff_sid");
    expect(cleared?.value).toBe("");

    const followUp = await app.fastify.inject({
      method: "GET",
      url: "/auth/session",
      headers: { cookie: cookies.join("; ") },
    });
    expect(followUp.json()).toEqual({ authenticated: false });
  });
});
