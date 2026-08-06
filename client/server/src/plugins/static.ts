// Location: ./client/server/src/plugins/static.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Serves the SPA build (`cd client && npm run build:bff` -> client/server/public/)
// and owns the SPA-fallback 404: any GET that isn't a real static asset or an
// already-registered API/auth/SSE route gets the app shell, so client-side
// routing survives a hard refresh on a deep link (/app/login, /app/tools, ...).
// Registered with fastify-plugin so both the `sendFile` decorator and the
// not-found handler apply at the true root, not just this plugin's own
// encapsulated context — routes/app.ts's GET / relies on `sendFile` too.
//
// The auth-aware '/' redirect itself lives in routes/app.ts, not here: this
// plugin's fallback always serves index.html unconditionally for anything
// under /app/*, deferring to the client router's own AuthGuard.

import path from "node:path";
import { fileURLToPath } from "node:url";

import fastifyStatic from "@fastify/static";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import fp from "fastify-plugin";

import { config } from "../config.js";

const DEFAULT_PUBLIC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../public");
const PUBLIC_DIR = config.publicDir ?? DEFAULT_PUBLIC_DIR;

export default fp(
  async function staticPlugin(fastify: FastifyInstance) {
    await fastify.register(fastifyStatic, {
      root: PUBLIC_DIR,
      prefix: "/",
      index: false, // '/' is handled explicitly by routes/app.ts, for the auth check
    });

    fastify.setNotFoundHandler((request: FastifyRequest, reply: FastifyReply) => {
      const pathname = request.url.split("?")[0] ?? request.url;
      // A missing asset (has a file extension, e.g. /assets/nope.js) is a
      // real 404, not a client route — only extension-less paths (client
      // router paths like /login, /tools/123) get the SPA fallback.
      const looksLikeAsset = /\.[a-zA-Z0-9]+$/.test(pathname);

      if (
        request.method !== "GET" ||
        pathname.startsWith("/api/") ||
        pathname.startsWith("/auth/") ||
        looksLikeAsset
      ) {
        return reply.code(404).send({
          message: `Route ${request.method}:${request.url} not found`,
          error: "Not Found",
          statusCode: 404,
        });
      }
      return reply.sendFile("index.html");
    });
  },
  { name: "staticPlugin" },
);
