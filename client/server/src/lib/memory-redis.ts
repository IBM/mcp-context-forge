// Location: ./client/server/src/lib/memory-redis.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0
//
// Zero-dependency in-process stand-in for ioredis, selected when
// REDIS_URL=memory:// — dev-only convenience so `pnpm dev` needs nothing
// running beyond FastAPI, same spirit as sqlite for `make dev`. Never use
// in production: state is lost on restart and isn't shared across
// processes, which defeats both session revocation and horizontal scaling.
//
// Store and pub/sub bus are module-level singletons so every MemoryRedis
// instance in this process (the command client in plugins/redis.ts and the
// dedicated subscriber in routes/sse/revocation-subscriber.ts) sees the
// other's writes/publishes, exactly like two connections to one real Redis.

import { EventEmitter } from "node:events";

export const MEMORY_REDIS_URL_PREFIX = "memory://";

export function isMemoryRedisUrl(url: string): boolean {
  return url.startsWith(MEMORY_REDIS_URL_PREFIX);
}

interface StoredValue {
  value: string;
  expiresAt: number | null;
}

const store = new Map<string, StoredValue>();
const bus = new EventEmitter();
bus.setMaxListeners(0);

function isExpired(entry: StoredValue): boolean {
  return entry.expiresAt !== null && entry.expiresAt <= Date.now();
}

function globToRegExp(pattern: string): RegExp {
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

export class MemoryRedis extends EventEmitter {
  async get(key: string): Promise<string | null> {
    const entry = store.get(key);
    if (!entry || isExpired(entry)) {
      if (entry) store.delete(key);
      return null;
    }
    return entry.value;
  }

  async setex(key: string, ttlSeconds: number, value: string): Promise<"OK"> {
    store.set(key, { value, expiresAt: Date.now() + ttlSeconds * 1000 });
    return "OK";
  }

  async del(key: string): Promise<number> {
    return store.delete(key) ? 1 : 0;
  }

  async publish(channel: string, message: string): Promise<number> {
    const before = bus.listenerCount("publish");
    bus.emit("publish", channel, message);
    return before;
  }

  // Mirrors ioredis's variadic signature: one or more patterns, optional
  // trailing (err, count) callback.
  async psubscribe(
    ...args: Array<string | ((err: Error | null, count?: number) => void)>
  ): Promise<number> {
    const patterns = args.filter((a): a is string => typeof a === "string");
    const callback = args.find(
      (a): a is (err: Error | null, count?: number) => void => typeof a === "function",
    );

    for (const pattern of patterns) {
      const regex = globToRegExp(pattern);
      bus.on("publish", (channel: string, message: string) => {
        if (regex.test(channel)) this.emit("pmessage", pattern, channel, message);
      });
    }

    callback?.(null, patterns.length);
    return patterns.length;
  }

  async quit(): Promise<"OK"> {
    this.removeAllListeners();
    return "OK";
  }
}
