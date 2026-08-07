// Location: ./client/server/src/lib/session-store.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Opaque session_id -> { bearerToken, user } in Redis. The browser only ever
// sees the session_id (HttpOnly cookie); the bearer token never leaves the BFF.

import { randomUUID } from "node:crypto";

import type { FastifyReply } from "fastify";

import { config } from "../config.js";

export const SESSION_COOKIE_NAME = "bff_sid";

// Structural subset of the ioredis client this module actually calls.
// Avoids coupling to @fastify/redis's decorated instance type (which wraps
// ioredis with its own generics) and lets tests pass an in-memory fake.
export interface RedisLike {
  get(key: string): Promise<string | null>;
  setex(key: string, ttlSeconds: number, value: string): Promise<unknown>;
  del(key: string): Promise<unknown>;
  publish(channel: string, message: string): Promise<unknown>;
}

// Passthrough of the upstream API's user object (EmailUserResponse — email,
// full_name, is_admin, is_active, auth_provider, email_verified,
// password_change_required, ...). The BFF doesn't interpret these fields —
// it stores and echoes back whatever FastAPI returned, snake_case included,
// so the SPA's User type (client/src/auth/AuthContext.tsx) matches without
// a translation layer that would drift as the upstream schema evolves.
export interface SessionUser {
  email: string;
  [key: string]: unknown;
}

export interface SessionRecord {
  bearerToken: string;
  user: SessionUser;
}

export function sessionRedisKey(sessionId: string): string {
  return `bff:session:${sessionId}`;
}

/** Publish channel for cross-instance revocation (see routes/sse/revocation-subscriber.ts). */
export function sessionRevokedChannel(sessionId: string): string {
  return `bff:session:revoked:${sessionId}`;
}

// TTL defaults to config.sessionTtlSeconds, but callers should pass the
// upstream token's real expires_in (see routes/auth/login.ts) — the BFF
// session and cookie must not outlive the bearer token they wrap. A session
// that looks valid for 24h while the JWT died in 20 minutes just means
// every call in between silently 401s until the proxy's own revoke-on-401
// catches it (see routes/proxy/catch-all.ts); matching the TTL up front
// avoids that window entirely.
export async function createSession(
  redis: RedisLike,
  record: SessionRecord,
  ttlSeconds: number = config.sessionTtlSeconds,
): Promise<string> {
  const sessionId = randomUUID();
  await redis.setex(sessionRedisKey(sessionId), ttlSeconds, JSON.stringify(record));
  return sessionId;
}

export async function getSession(
  redis: RedisLike,
  sessionId: string,
): Promise<SessionRecord | null> {
  const raw = await redis.get(sessionRedisKey(sessionId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionRecord;
  } catch {
    return null;
  }
}

export async function deleteSession(redis: RedisLike, sessionId: string): Promise<void> {
  await redis.del(sessionRedisKey(sessionId));
  // Best-effort fan-out so any BFF instance holding an open SSE socket for
  // this session aborts it promptly. No subscribers = no-op; not required
  // for correctness (see Option A staleness re-check in the SSE proxy).
  await redis.publish(sessionRevokedChannel(sessionId), "1");
}

export function setSessionCookie(
  reply: FastifyReply,
  sessionId: string,
  maxAgeSeconds: number = config.sessionTtlSeconds,
): void {
  reply.setCookie(SESSION_COOKIE_NAME, sessionId, {
    httpOnly: true,
    secure: config.cookieSecure,
    sameSite: "lax",
    path: "/",
    domain: config.cookieDomain,
    maxAge: maxAgeSeconds,
  });
}

export function clearSessionCookie(reply: FastifyReply): void {
  reply.clearCookie(SESSION_COOKIE_NAME, {
    path: "/",
    domain: config.cookieDomain,
  });
}
