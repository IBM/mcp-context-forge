export interface User {
  email: string;
  full_name?: string;
  is_admin: boolean;
  is_active: boolean;
  auth_provider: string;
  created_at: string;
  updated_at?: string;
  last_login?: string;
  email_verified: boolean;
  password_change_required: boolean;
  failed_login_attempts: number;
  locked_until?: string;
  is_locked: boolean;
}

export interface CreateUserRequest {
  email: string;
  password: string; // pragma: allowlist secret
  full_name?: string;
  is_admin?: boolean;
  is_active?: boolean;
  password_change_required?: boolean;
}

export interface UpdateUserRequest {
  full_name?: string;
  is_admin?: boolean;
  is_active?: boolean;
  email_verified?: boolean;
  password_change_required?: boolean;
  password?: string; // pragma: allowlist secret
}

export interface UsersResponse {
  users: User[];
  nextCursor?: string;
}
