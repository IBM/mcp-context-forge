// Location: ./client/server/src/routes/sse/revocation-subscriber.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Cross-instance SSE revocation (Option B from agent-output/bff-proxy-and-sse-plan.md,
// layered on top of Option A's periodic re-check). A dedicated ioredis
// connection in subscribe mode — the command client decorated by
// plugins/redis.ts can't issue normal commands once subscribed, hence the
// separate connection here. REDIS_URL=memory:// swaps in the in-process
// MemoryRedis (see plugins/redis.ts) instead — irrelevant for a single dev
// process, but kept symmetric with the command client's mode.

import { Redis } from "ioredis";

import { config } from "../../config.js";
import { isMemoryRedisUrl, MemoryRedis } from "../../lib/memory-redis.js";
import { abortAll } from "./registry.js";

const REVOKED_PATTERN = "bff:session:revoked:*";

function onPmessage(_pattern: string, channel: string): void {
  const sessionId = channel.slice("bff:session:revoked:".length);
  if (sessionId) abortAll(sessionId);
}

export function startRevocationSubscriber(): Redis | MemoryRedis {
  const subscriber = isMemoryRedisUrl(config.redisUrl)
    ? new MemoryRedis()
    : new Redis(config.redisUrl);

  subscriber.psubscribe(REVOKED_PATTERN, (err) => {
    if (err) {
      subscriber.emit("error", err);
    }
  });

  subscriber.on("pmessage", onPmessage);

  return subscriber;
}
