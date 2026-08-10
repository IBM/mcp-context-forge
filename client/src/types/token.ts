/**
 * API token types.
 *
 * Re-exports the generated OpenAPI shapes so the tokens feature imports from a
 * single, stable module rather than reaching into `@/generated/types/*`.
 */

export type { TokenResponse } from "@/generated/types/tokenResponse";
export type { TokenCreateRequest } from "@/generated/types/tokenCreateRequest";
export type { TokenCreateResponse } from "@/generated/types/tokenCreateResponse";
export type { TokenListResponse } from "@/generated/types/tokenListResponse";
export type { TokenScopeRequest } from "@/generated/types/tokenScopeRequest";
