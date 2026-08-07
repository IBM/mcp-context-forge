// Location: ./client/server/src/lib/sse-headers.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Response headers for a hijacked SSE passthrough. Replicates what
// infra/nginx/nginx.conf's SSE location blocks do for the browser<->nginx
// hop (no buffering, no compression, indefinite keep-alive) — there's no
// nginx sitting between the BFF and FastAPI, so the BFF has to do it itself.

import type { ServerResponse } from "node:http";

export function writeSseHeaders(res: ServerResponse): void {
  res.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    connection: "keep-alive",
    "x-accel-buffering": "no", // belt-and-suspenders if nginx ever ends up in front of the BFF too
  });
  res.flushHeaders?.();
}
