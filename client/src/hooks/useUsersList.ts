import { useMemo } from "react";
import { useQuery } from "@/hooks/useQuery";
import type { UsersResponse } from "@/types/user";

export interface UseUsersListOptions {
  cursor?: string;
  limit?: number;
  enabled?: boolean;
  immediate?: boolean;
}

export function useUsersList({
  cursor,
  limit,
  enabled = true,
  immediate = true,
}: UseUsersListOptions = {}) {
  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(Math.min(100, Math.max(1, limit))));
    params.set("include_pagination", "true");
    return `/auth/email/admin/users?${params.toString()}`;
  }, [cursor, limit]);

  return useQuery<UsersResponse>(path, { enabled, immediate });
}
