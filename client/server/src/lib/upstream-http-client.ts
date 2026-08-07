// Location: ./client/server/src/lib/upstream-http-client.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Dedicated undici pool for long-lived SSE upstream connections, separate
// from @fastify/reply-from's pool (used by the generic /api/* catch-all).
// SSE needs headersTimeout/bodyTimeout disabled; that must not leak into the
// pool used for normal short-lived request/response calls.
// See agent-output/bff-proxy-and-sse-plan.md, "Why hand-rolled ... for SSE".

import { Pool } from "undici";

import { config } from "../config.js";

export const sseUpstreamPool = new Pool(config.fastapiUrl, {
  headersTimeout: 0,
  bodyTimeout: 0,
});
