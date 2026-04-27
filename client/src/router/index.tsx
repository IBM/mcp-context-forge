/**
 * Minimal client-side router — hardened against common web vulnerabilities.
 *
 * Security properties:
 *   - All navigation destinations are validated to be internal /app/* paths.
 *     Attempts to navigate outside /app/ (including path traversal like
 *     /app/../admin) are silently dropped.
 *   - Route params are decoded with a safe wrapper; malformed percent-encoding
 *     never crashes the router.
 *   - There is no module-level navigate() export. The 401 redirect in
 *     api/client.ts uses window.location.replace() directly, which is the
 *     correct primitive (replaces history, no back-button loop, no React
 *     state race).
 *   - AuthGuard accepts an explicit allowlist of public paths so access
 *     control is opt-in, not opt-out.
 *
 * Public API:
 *   <RouterProvider>               — wraps the app
 *   <Route path="" component={} /> — renders on match
 *   <Redirect to="" />             — navigates on mount (validated)
 *   <AuthGuard publicPaths={[]} publicPrefixes={[]}/>  — blocks unauthenticated access
 *   useRouter()                    — { path, params, navigate }
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { getToken } from "../api/client";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const APP_PREFIX = "/app";

// ---------------------------------------------------------------------------
// Destination validation
//
// Accepts only paths that:
//   1. Start with /app/ or are exactly /app
//   2. Do not contain ..  (path traversal)
//   3. Do not contain :// (protocol injection)
// Returns the normalised path, or null when the destination is rejected.
// ---------------------------------------------------------------------------

function validateDestination(to: string): string | null {
  if (typeof to !== "string") return null;

  // Reject anything that looks like a URL with a protocol
  if (/[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(to)) return null;
  // Reject protocol-relative URLs
  if (to.startsWith("//")) return null;
  // Reject path traversal sequences
  if (to.includes("..")) return null;

  const isAppPath = to === APP_PREFIX || to.startsWith(APP_PREFIX + "/");
  if (!isAppPath) return null;

  return to;
}

// ---------------------------------------------------------------------------
// Safe param decoding
// decodeURIComponent throws a URIError on malformed percent-sequences.
// ---------------------------------------------------------------------------

function safeDecodeParam(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RouterState {
  path: string;
  params: Record<string, string>;
}

interface RouterContextValue extends RouterState {
  navigate: (to: string) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const RouterContext = createContext<RouterContextValue | null>(null);

// ---------------------------------------------------------------------------
// Path matching
// Maps a pattern like "/app/users/:id" against a concrete path.
// Returns params or null when there is no match or a param is malformed.
// ---------------------------------------------------------------------------

function matchPath(pattern: string, path: string): Record<string, string> | null {
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = path.split("/").filter(Boolean);

  if (patternParts.length !== pathParts.length) return null;

  const params: Record<string, string> = {};

  for (let i = 0; i < patternParts.length; i++) {
    const pp = patternParts[i]!;
    const sp = pathParts[i]!;
    if (pp.startsWith(":")) {
      const decoded = safeDecodeParam(sp);
      if (decoded === null) return null; // malformed param → no match
      params[pp.slice(1)] = decoded;
    } else if (pp !== sp) {
      return null;
    }
  }

  return params;
}

// ---------------------------------------------------------------------------
// RouterProvider
// ---------------------------------------------------------------------------

export function RouterProvider({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname);

  const navigate = useCallback((to: string) => {
    const safe = validateDestination(to);
    if (safe === null) {
      // Destination rejected — do nothing and warn in development
      if (import.meta.env.DEV) {
        console.warn(`[router] Navigation to "${to}" was blocked: not a valid /app/* path.`);
      }
      return;
    }
    window.history.pushState(null, "", safe);
    setPath(safe);
  }, []);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const value = useMemo<RouterContextValue>(
    () => ({ path, params: {}, navigate }),
    [path, navigate],
  );

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

// ---------------------------------------------------------------------------
// useRouter
// ---------------------------------------------------------------------------

export function useRouter(): RouterContextValue {
  const ctx = useContext(RouterContext);
  if (!ctx) throw new Error("useRouter must be used inside <RouterProvider>");
  return ctx;
}

// ---------------------------------------------------------------------------
// Route
// ---------------------------------------------------------------------------

interface RouteProps {
  path: string;
  component: ComponentType<Record<string, string>>;
}

export function Route({ path: pattern, component: Component }: RouteProps) {
  const { path } = useRouter();
  const params = matchPath(pattern, path);
  if (params === null) return null;
  return <Component {...params} />;
}

// ---------------------------------------------------------------------------
// Redirect
// Validates the destination before navigating.
// ---------------------------------------------------------------------------

export function Redirect({ to }: { to: string }) {
  const { navigate } = useRouter();
  useEffect(() => {
    navigate(to);
  }, [navigate, to]);
  return null;
}

// ---------------------------------------------------------------------------
// AuthGuard
//
// Blocks unauthenticated access to protected routes.
// publicPaths is an explicit allowlist — access control is opt-in, not
// opt-out, so adding a new public route requires a deliberate declaration.
// ---------------------------------------------------------------------------

// Exact paths that are always public.
const DEFAULT_PUBLIC_PATHS: readonly string[] = [
  "/app/loading",
  "/app/login",
  "/app/forgot-password",
];

// Path prefixes whose subtrees are always public.
const DEFAULT_PUBLIC_PREFIXES: readonly string[] = ["/app/reset-password/"];

interface AuthGuardProps {
  children: ReactNode;
  /** Exact paths that do not require authentication. Defaults to login + forgot-password. */
  publicPaths?: readonly string[];
  /** Path prefixes whose subtrees do not require authentication. */
  publicPrefixes?: readonly string[];
}

export function AuthGuard({
  children,
  publicPaths = DEFAULT_PUBLIC_PATHS,
  publicPrefixes = DEFAULT_PUBLIC_PREFIXES,
}: AuthGuardProps) {
  const { navigate, path } = useRouter();
  const authenticated = getToken() !== null;

  const isPublic =
    publicPaths.includes(path) || publicPrefixes.some((prefix) => path.startsWith(prefix));

  useEffect(() => {
    if (!authenticated && !isPublic) {
      navigate("/app/login");
    }
  }, [authenticated, isPublic, navigate]);

  if (isPublic || !authenticated) return null;
  return <>{children}</>;
}
