import { http, HttpResponse } from "msw";

export const handlers = [
  // Mock login endpoint
  http.post("/auth/login", async ({ request }) => {
    const body = await request.json();
    const { email, password } = body as { email: string; password: string };

    // Simple mock validation
    if (
      email === "test@example.com" &&
      password === "password123" // pragma: allowlist secret
    ) {
      return HttpResponse.json({
        access_token: "mock-token-12345",
        token_type: "bearer",
        expires_in: 3600,
        user: {
          email: "test@example.com",
          full_name: "Test User",
          is_admin: true,
          is_active: true,
          auth_provider: "local",
          email_verified: true,
          password_change_required: false,
        },
      });
    }

    return HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 });
  }),

  // Mock auth check endpoint
  http.get("/auth/me", () => {
    return HttpResponse.json({
      email: "test@example.com",
      full_name: "Test User",
      is_admin: true,
      is_active: true,
      auth_provider: "local",
      email_verified: true,
      password_change_required: false,
    });
  }),

  // Mock gateways endpoint with cursor pagination
  http.get("/gateways", ({ request }) => {
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

  // Mock gateway delete endpoint
  http.delete("/gateways/:id", () => {
    return HttpResponse.json({ success: true });
  }),

  // Mock gateway test endpoint
  http.post("/gateways/:id/test", () => {
    return HttpResponse.json({
      success: true,
      message: "Connection successful",
    });
  }),

  // Mock create gateway endpoint
  http.post("/gateways", async ({ request }) => {
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
  http.put("/gateways/:gatewayId", async ({ request, params }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const { gatewayId } = params;
    return HttpResponse.json({
      id: gatewayId,
      ...body,
      updated_at: new Date().toISOString(),
    });
  }),
];
