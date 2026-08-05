/**
 * Recent Activity API service
 *
 * Wraps GET /api/logs/activity. The endpoint is planned (Option A first,
 * forward-compatible to Option B SSE) — callers should treat it as
 * standard polling for now and migrate to the stream endpoint later
 * without changing this client.
 */

import { api } from "./client";
import type { ActivityListResponse } from "../types/activity";

export const activityApi = {
  /**
   * List recent activity items.
   *
   * @param params.limit Max items to return (server clamps).
   * @param params.since ISO 8601 timestamp — only return items strictly after.
   */
  list: (params?: {
    limit?: number;
    since?: string;
    signal?: AbortSignal;
  }): Promise<ActivityListResponse> => {
    const searchParams = new URLSearchParams();

    if (params?.limit !== undefined) {
      const limit = Number.isFinite(params.limit)
        ? Math.max(1, Math.min(100, Math.floor(params.limit)))
        : 10;
      searchParams.set("limit", limit.toString());
    }

    if (params?.since) {
      searchParams.set("since", params.since);
    }

    const query = searchParams.toString();
    return api.get(`/api/logs/activity${query ? `?${query}` : ""}`, undefined, params?.signal);
  },
};
