export interface Team {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_by: string;
  is_personal: boolean;
  visibility: "private" | "public";
  max_members?: number;
  member_count: number;
  created_at: string;
  updated_at: string;
  is_active: boolean;
}

export interface TeamsResponse {
  teams: Team[];
  nextCursor?: string;
}
