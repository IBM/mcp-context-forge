// Location: ./client/server/src/routes/sse/revocation-subscriber.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Cross-instance SSE revocation (Option B from agent-output/bff-proxy-and-sse-plan.md,
// layered on top of Option A's periodic re-check). A dedicated ioredis
// connection in subscribe mode — the command client decorated by
// plugins/redis.ts can't issue normal commands once subscribed, hence the
// separate connection here.

import { Redis } from "ioredis";

import { config } from "../../config.js";
import { abortAll } from "./registry.js";

const REVOKED_PATTERN = "bff:session:revoked:*";

export function startRevocationSubscriber(): Redis {
  const subscriber = new Redis(config.redisUrl);

  subscriber.psubscribe(REVOKED_PATTERN, (err) => {
    if (err) {
      subscriber.emit("error", err);
    }
  });

  subscriber.on("pmessage", (_pattern: string, channel: string) => {
    const sessionId = channel.slice("bff:session:revoked:".length);
    if (sessionId) abortAll(sessionId);
  });

  return subscriber;
}
