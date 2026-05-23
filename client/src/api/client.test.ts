import { afterEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { api } from "./client";
import { server } from "@/test/mocks/server";

function clearCookie(name: string) {
  document.cookie = `${name}=; Max-Age=0; path=/`;
}

describe("api client", () => {
  afterEach(() => {
    clearCookie("mcpgateway_csrf_token");
    clearCookie("csrf_token");
  });

  it("sends X-CSRF-Token from the configured mcpgateway CSRF cookie", async () => {
    document.cookie = "mcpgateway_csrf_token=new-token; path=/";

    let csrfHeader: string | null = null;
    server.use(
      http.post("*/csrf-check", ({ request }) => {
        csrfHeader = request.headers.get("X-CSRF-Token");
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.post("/csrf-check", {});

    expect(csrfHeader).toBe("new-token");
  });

  it("does not use legacy csrf_token cookies", async () => {
    document.cookie = "csrf_token=legacy-token; path=/";

    let csrfHeader: string | null = null;
    server.use(
      http.post("*/csrf-check", ({ request }) => {
        csrfHeader = request.headers.get("X-CSRF-Token");
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.post("/csrf-check", {});

    expect(csrfHeader).toBeNull();
  });
});
