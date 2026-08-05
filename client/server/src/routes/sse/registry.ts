// Location: ./client/server/src/routes/sse/registry.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Tracks live upstream SSE sockets per session on this BFF instance, so
// logout / revocation can abort them and browser disconnect can unregister
// them. Keyed by a Set, not a single controller — one session can have
// multiple concurrent SSE subscriptions open (resources, future db-records).
// Revocation must abort all of them. This registry is process-local by
// design: session state lives in Redis, sockets live on whichever BFF
// instance the browser's long-lived connection landed on.

const sessionSockets = new Map<string, Set<AbortController>>();

export function register(sessionId: string, controller: AbortController): void {
  let sockets = sessionSockets.get(sessionId);
  if (!sockets) {
    sockets = new Set();
    sessionSockets.set(sessionId, sockets);
  }
  sockets.add(controller);
}

export function unregister(sessionId: string, controller: AbortController): void {
  const sockets = sessionSockets.get(sessionId);
  if (!sockets) return;
  sockets.delete(controller);
  if (sockets.size === 0) sessionSockets.delete(sessionId);
}

/** Abort every open SSE socket for a session (logout / revocation). */
export function abortAll(sessionId: string): void {
  const sockets = sessionSockets.get(sessionId);
  if (!sockets) return;
  for (const controller of sockets) controller.abort();
  sessionSockets.delete(sessionId);
}

/** Test-only: count of currently-registered sockets for a session. */
export function socketCount(sessionId: string): number {
  return sessionSockets.get(sessionId)?.size ?? 0;
}
