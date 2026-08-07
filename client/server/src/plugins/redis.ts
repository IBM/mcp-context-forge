// Location: ./client/server/src/plugins/redis.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Decorates fastify.redis with a command client (GET/SETEX/DEL for session
// storage, PUBLISH for revocation). The dedicated subscriber connection used
// by SSE revocation lives separately in routes/sse/revocation-subscriber.ts —
// ioredis connections in subscribe mode can't issue normal commands.
//
// REDIS_URL=memory:// swaps in an in-process store (lib/memory-redis.ts) —
// dev-only, no Redis process required, same spirit as sqlite for `make dev`.

import fastifyRedis from "@fastify/redis";
import type { FastifyInstance } from "fastify";
import fp from "fastify-plugin";

import { config } from "../config.js";
import { isMemoryRedisUrl, MemoryRedis } from "../lib/memory-redis.js";

export default fp(
  async function redisPlugin(fastify: FastifyInstance) {
    if (isMemoryRedisUrl(config.redisUrl)) {
      fastify.log.warn(
        "REDIS_URL=memory:// — using an in-process session store. Dev only: state is lost on restart and not shared across instances.",
      );
      const memoryRedis = new MemoryRedis();
      fastify.decorate("redis", memoryRedis as unknown as FastifyInstance["redis"]);
      fastify.addHook("onClose", async () => {
        await memoryRedis.quit();
      });
      return;
    }

    await fastify.register(fastifyRedis, {
      url: config.redisUrl,
      closeClient: true,
    });
  },
  { name: "redisPlugin" },
);
