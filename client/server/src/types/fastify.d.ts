// Location: ./client/server/src/types/fastify.d.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0

import "fastify";

import type { SessionUser } from "../lib/session-store.js";

export interface BffSession {
  sessionId: string;
  bearerToken: string;
  user: SessionUser;
}

declare module "fastify" {
  interface FastifyRequest {
    /** Populated by the session preHandler. Absent on unauthenticated routes. */
    session?: BffSession;
  }
}
