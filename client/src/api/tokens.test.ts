import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { tokensApi } from "./tokens";

describe("tokensApi", () => {
  describe("list", () => {
    it("GETs /tokens and returns the list response", async () => {
      const payload = { tokens: [], total: 0, limit: 0, offset: 0 };
      server.use(http.get("*/tokens", () => HttpResponse.json(payload)));

      const result = await tokensApi.list();

      expect(result).toEqual(payload);
    });
  });

  describe("create", () => {
    it("POSTs the payload to /tokens and returns the one-time secret", async () => {
      let received: unknown;
      const created = { access_token: "raw-secret", token: { id: "tok-1", name: "CI" } };
      server.use(
        http.post("*/tokens", async ({ request }) => {
          received = await request.json();
          return HttpResponse.json(created, { status: 201 });
        }),
      );
      const body = { name: "CI", expires_in_days: 30, team_id: "team-1" };

      const result = await tokensApi.create(body);

      expect(received).toEqual(body);
      expect(result).toEqual(created);
    });
  });

  describe("delete", () => {
    it("DELETEs /tokens/{id} with a URL-encoded id", async () => {
      let calledPath = "";
      server.use(
        http.delete("*/tokens/:id", ({ request }) => {
          calledPath = new URL(request.url).pathname;
          return new HttpResponse(null, { status: 204 });
        }),
      );

      await tokensApi.delete("id/with space");

      expect(calledPath).toMatch(/\/tokens\/id%2Fwith%20space$/);
    });
  });
});
