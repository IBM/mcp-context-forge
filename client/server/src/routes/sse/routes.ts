// Location: ./client/server/src/routes/sse/routes.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Concrete SSE route registrations. Both go through the same
// registerSseProxyRoute factory despite the upstream method mismatch
// (resources/subscribe is POST-only upstream, roots/changes is GET) —
// proof the factory is genuinely generic, not a one-off for that mismatch.
// Add future SSE streams (e.g. a db-records subscription) here.

import type { FastifyInstance } from "fastify";

import { registerSseProxyRoute } from "./proxy-sse.js";

export default async function sseRoutes(fastify: FastifyInstance): Promise<void> {
  registerSseProxyRoute(fastify, {
    browserPath: "/api/resources/subscribe",
    upstreamPath: "/resources/subscribe",
    upstreamMethod: "POST",
  });

  registerSseProxyRoute(fastify, {
    browserPath: "/api/roots/changes",
    upstreamPath: "/roots/changes",
    upstreamMethod: "GET",
  });
}
