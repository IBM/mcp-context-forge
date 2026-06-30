import { api } from "@/api/client";

export function deleteTeam(id: string): Promise<void> {
  return api.delete<void>(`/teams/${encodeURIComponent(id)}`);
}
