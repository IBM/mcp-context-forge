// Location: ./client/server/src/plugins/redis.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Decorates fastify.redis with a command client (GET/SETEX/DEL for session
// storage, PUBLISH for revocation). The dedicated subscriber connection used
// by SSE revocation lives separately in routes/sse/revocation-subscriber.ts —
// ioredis connections in subscribe mode can't issue normal commands.

import fastifyRedis from "@fastify/redis";
import type { FastifyInstance } from "fastify";
import fp from "fastify-plugin";

import { config } from "../config.js";

export default fp(
  async function redisPlugin(fastify: FastifyInstance) {
    await fastify.register(fastifyRedis, {
      url: config.redisUrl,
      closeClient: true,
    });
  },
  { name: "redisPlugin" },
);
