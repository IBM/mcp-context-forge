import { http, HttpResponse } from "msw";

import { RECENT_ACTIVITY_FIXTURE } from "@/mocks/recentActivity";

export const handlers = [
  // Mock Recent Activity endpoint — backed by RECENT_ACTIVITY_FIXTURE.
  http.get("*/api/logs/activity", ({ request }) => {
    const url = new URL(request.url);
    const limitParam = url.searchParams.get("limit");
    const since = url.searchParams.get("since");

    const parsedLimit = limitParam ? parseInt(limitParam, 10) : 10;
    const limit = Number.isFinite(parsedLimit) ? Math.max(1, Math.min(100, parsedLimit)) : 10;

    let items = RECENT_ACTIVITY_FIXTURE;
    if (since) {
      const sinceMs = Date.parse(since);
      if (!Number.isNaN(sinceMs)) {
        items = items.filter((item) => Date.parse(item.timestamp) > sinceMs);
      }
    }

    return HttpResponse.json({ items: items.slice(0, limit) });
  }),

  // Mock login endpoint (BFF-owned, not proxied through /api)
  http.post("*/auth/login", async ({ request }) => {
    const body = await request.json();
    const { email, password } = body as { email: string; password: string }; // pragma: allowlist secret

    // Simple mock validation
    if (
      email === "test@example.com" &&
      password === "password123" // pragma: allowlist secret
    ) {
      return HttpResponse.json({
        user: {
          email: "test@example.com",
          full_name: "Test User",
          is_admin: true,
          is_active: true,
          auth_provider: "local",
          email_verified: true,
          password_change_required: false,
        },
        csrfToken: "mock-csrf-token",
      });
    }

    return HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 });
  }),

  // Mock session-check endpoint (BFF-owned) — always 200, unauthenticated by default
  http.get("*/auth/session", () => {
    return HttpResponse.json({ authenticated: false });
  }),

  // Mock gateways endpoint with cursor pagination
  http.get("*/api/gateways", ({ request }) => {
    const url = new URL(request.url);
    const cursor = url.searchParams.get("cursor");
    const limit = parseInt(url.searchParams.get("limit") || "25", 10);

    const allServers = Array.from({ length: 50 }, (_, i) => ({
      id: `server-${i}`,
      name: `Test Server ${i}`,
      url: `http://localhost:${3000 + i}`,
      transport: "SSE" as const,
      enabled: true,
      reachable: true,
      tool_count: 5,
      visibility: "public" as const,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    }));

    const startIndex = cursor ? parseInt(cursor, 10) : 0;
    const endIndex = Math.min(startIndex + limit, allServers.length);
    const gateways = allServers.slice(startIndex, endIndex);
    const nextCursor = endIndex < allServers.length ? endIndex.toString() : null;

    return HttpResponse.json({
      gateways,
      nextCursor,
    });
  }),

  // Mock single gateway fetch endpoint
  http.get("*/api/gateways/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Test Server",
      url: "http://localhost:9000",
      transport: "STREAMABLEHTTP",
      visibility: "public",
      authType: "none",
    });
  }),

  // Mock gateway delete endpoint
  http.delete("*/api/gateways/:id", () => {
    return HttpResponse.json({ success: true });
  }),

  // Mock gateway test endpoint
  http.post("*/api/gateways/:id/test", () => {
    return HttpResponse.json({
      success: true,
      message: "Connection successful",
    });
  }),

  // Mock create gateway endpoint
  http.post("*/api/gateways", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: "mock-gateway-id",
        ...body,
        created_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),

  // Mock update gateway endpoint
  http.put("*/api/gateways/:gatewayId", async ({ request, params }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const { gatewayId } = params;
    return HttpResponse.json({
      id: gatewayId,
      ...body,
      updated_at: new Date().toISOString(),
    });
  }),

  // Default empty collections so page smoke tests that render these pages without
  // an explicit override don't hit unhandled requests. Specific tests still
  // override these via server.use(...).
  http.get("*/api/prompts", () => HttpResponse.json([])),

  http.get("*/api/resources", () => HttpResponse.json([])),

  http.get("*/api/teams", () => HttpResponse.json({ teams: [] })),
];
