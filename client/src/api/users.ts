import { api } from "./client";
import type { UsersResponse } from "../types/user";

export const usersApi = {
  list: (params?: {
    cursor?: string;
    limit?: number;
    signal?: AbortSignal;
  }): Promise<UsersResponse> => {
    const searchParams = new URLSearchParams();

    if (params?.cursor) {
      searchParams.set("cursor", params.cursor);
    }

    if (params?.limit !== undefined) {
      const limit = Number.isFinite(params.limit)
        ? Math.max(1, Math.min(100, Math.floor(params.limit)))
        : 25;
      searchParams.set("limit", limit.toString());
    }

    searchParams.set("include_pagination", "true");

    const query = searchParams.toString();
    return api.get(`/auth/email/admin/users${query ? `?${query}` : ""}`, undefined, params?.signal);
  },
};
