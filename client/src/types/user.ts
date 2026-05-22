export interface User {
  email: string;
  full_name?: string | null;
  is_admin: boolean;
  is_active: boolean;
  auth_provider: string;
  created_at: string;
  last_login?: string | null;
  email_verified: boolean;
  password_change_required: boolean;
  failed_login_attempts: number;
  locked_until?: string | null;
  is_locked: boolean;
}

export interface UsersResponse {
  users: User[];
  nextCursor?: string | null;
}
