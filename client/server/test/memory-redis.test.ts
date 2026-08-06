// Location: ./client/server/test/memory-redis.test.ts
// Copyright contributors to the MCP-CONTEXT-FORGE project
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it, vi } from "vitest";

import { MemoryRedis } from "../src/lib/memory-redis.js";

describe("MemoryRedis", () => {
  it("round-trips get/setex/del", async () => {
    const redis = new MemoryRedis();
    expect(await redis.get("k")).toBeNull();

    await redis.setex("k", 60, "v");
    expect(await redis.get("k")).toBe("v");

    expect(await redis.del("k")).toBe(1);
    expect(await redis.get("k")).toBeNull();
    expect(await redis.del("k")).toBe(0);
  });

  it("expires keys after their TTL", async () => {
    vi.useFakeTimers();
    try {
      const redis = new MemoryRedis();
      await redis.setex("k", 1, "v");
      expect(await redis.get("k")).toBe("v");

      vi.advanceTimersByTime(1001);
      expect(await redis.get("k")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("delivers publish() to a matching psubscribe() pattern across instances", async () => {
    const subscriber = new MemoryRedis();
    const publisher = new MemoryRedis();
    const received: Array<[string, string, string]> = [];

    await subscriber.psubscribe("bff:session:revoked:*");
    subscriber.on("pmessage", (pattern: string, channel: string, message: string) => {
      received.push([pattern, channel, message]);
    });

    await publisher.publish("bff:session:revoked:abc123", "1");
    await publisher.publish("some:other:channel", "ignored");

    expect(received).toEqual([["bff:session:revoked:*", "bff:session:revoked:abc123", "1"]]);
  });
});
