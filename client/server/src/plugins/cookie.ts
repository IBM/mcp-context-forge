// Location: ./client/server/src/plugins/cookie.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0

import fastifyCookie from "@fastify/cookie";
import type { FastifyInstance } from "fastify";
import fp from "fastify-plugin";

export default fp(
  async function cookiePlugin(fastify: FastifyInstance) {
    await fastify.register(fastifyCookie);
  },
  { name: "cookiePlugin" },
);
