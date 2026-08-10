/**
 * API tokens service.
 *
 * Wraps the self-service `/tokens` endpoints (the caller acting on their own
 * tokens). Token CRUD is gated server-side by an interactive-session check, so
 * these calls only succeed from inside the authenticated `/app` shell (session
 * cookie + CSRF header, supplied by the shared api client).
 */

import { api } from "./client";
import type { TokenCreateRequest, TokenCreateResponse, TokenListResponse } from "@/types/token";

export const tokensApi = {
  /** List the caller's own tokens. */
  list: (signal?: AbortSignal): Promise<TokenListResponse> =>
    api.get<TokenListResponse>("/tokens", undefined, signal),

  /**
   * Create a token. The raw `access_token` is only present on this response and
   * is never retrievable again.
   */
  create: (payload: TokenCreateRequest): Promise<TokenCreateResponse> =>
    api.post<TokenCreateResponse>("/tokens", payload),

  /**
   * Revoke (delete) a token by id. Access is cut immediately and cannot be
   * undone. The backend records a default revocation reason.
   */
  delete: (id: string): Promise<void> => api.delete<void>(`/tokens/${encodeURIComponent(id)}`),
};
