import { useCallback, useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { api } from "@/api/client";

type QueryMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface QueryError {
  message: string;
  code?: string;
  status?: number;
  body?: unknown;
}

interface UseQueryOptions<TData, TBody = unknown> {
  method?: QueryMethod;
  enabled?: boolean;
  immediate?: boolean;
  initialData?: TData;
  body?: TBody;
  headers?: Record<string, string>;
  timeout?: number; // milliseconds, default 30000
}

interface UseQueryResult<TData, TBody = unknown> {
  /** Most recently fetched data, or `undefined` before the first successful load. */
  data: TData | undefined;
  /** Error from the last failed request, or `null` if the last request succeeded. */
  error: QueryError | null;
  /** Whether a request is currently in flight. */
  isLoading: boolean;
  /** Runs the query, optionally overriding the request body. Resolves with the fetched data. */
  execute: (overrideBody?: TBody) => Promise<TData>;
  /** Re-runs the last query with the same parameters. Resolves with the fetched data. */
  refetch: () => Promise<TData>;
  /** Imperatively patches the cached data in place after a mutation (avoiding a full refetch). Supports functional updates. */
  setData: Dispatch<SetStateAction<TData | undefined>>;
}

function sanitizeError(err: unknown): QueryError {
  if (err instanceof Error) {
    const errorObj = err as Error & { status?: number; code?: string; body?: unknown };
    return {
      message: errorObj.message,
      status: errorObj.status,
      code: errorObj.code,
      body: errorObj.body,
    };
  }
  return { message: "An unexpected error occurred" };
}

function createHeadersKey(headers?: Record<string, string>): string {
  if (!headers) return "";
  return JSON.stringify(
    Object.entries(headers).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function createBodyKey(body: unknown): string {
  if (body === undefined) return "";
  try {
    // Use replacer to handle circular refs and prevent prototype pollution
    return JSON.stringify(body, (key, value) => {
      if (key === "__proto__" || key === "constructor") return undefined;
      return value;
    });
  } catch (err) {
    console.warn("Failed to serialize body for cache key:", err);
    return `[unserializable-${Date.now()}]`;
  }
}

async function executeRequest<TData, TBody>(
  path: string,
  method: QueryMethod,
  headers?: Record<string, string>,
  body?: TBody,
  timeout = 30000,
  externalSignal?: AbortSignal,
): Promise<TData> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // If external signal is provided, abort our controller when it aborts
  if (externalSignal) {
    externalSignal.addEventListener("abort", () => controller.abort());
  }

  try {
    switch (method) {
      case "GET":
        return await api.get<TData>(path, headers, controller.signal);
      case "POST":
        return await api.post<TData>(path, body, { headers, signal: controller.signal });
      case "PUT":
        return await api.put<TData>(path, body, { headers, signal: controller.signal });
      case "PATCH":
        return await api.patch<TData>(path, body, { headers, signal: controller.signal });
      case "DELETE":
        return await api.delete<TData>(path, { headers, signal: controller.signal });
      default: {
        const _exhaustive: never = method;
        throw new Error(`Unhandled method: ${_exhaustive}`);
      }
    }
  } finally {
    clearTimeout(timeoutId);
  }
}

export function useQuery<TData, TBody = unknown>(
  path: string | null,
  options: UseQueryOptions<TData, TBody> = {},
): UseQueryResult<TData, TBody> {
  // Validate inputs
  if (path !== null && (!path || typeof path !== "string")) {
    throw new Error("useQuery: path must be a non-empty string or null");
  }

  if (path?.startsWith("//")) {
    throw new Error("useQuery: path must be relative (no protocol)");
  }

  const {
    method = "GET",
    enabled = true,
    immediate,
    initialData,
    body,
    headers,
    timeout = 30000,
  } = options;

  const shouldFetchImmediately = immediate ?? method === "GET";
  const [data, setData] = useState<TData | undefined>(initialData);
  const [error, setError] = useState<QueryError | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(
    path !== null && enabled && shouldFetchImmediately && initialData === undefined,
  );

  const headersKey = useMemo(() => createHeadersKey(headers), [headers]);
  const bodyKey = useMemo(() => createBodyKey(body), [body]);

  const execute = useCallback(
    async (overrideBody?: TBody): Promise<TData> => {
      if (path === null) {
        throw new Error("useQuery: cannot execute a query without a path");
      }

      setIsLoading(true);
      setError(null);

      try {
        const result = await executeRequest<TData, TBody>(
          path,
          method,
          headers,
          overrideBody === undefined ? body : overrideBody,
          timeout,
        );
        setData(result);
        return result;
      } catch (err) {
        const sanitized = sanitizeError(err);
        setError(sanitized);
        throw sanitized;
      } finally {
        setIsLoading(false);
      }
    },
    // Using headersKey and bodyKey instead of headers/body to prevent unnecessary re-renders
    // when object references change but content remains the same
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, method, headersKey, bodyKey, timeout],
  );

  useEffect(() => {
    if (path === null || !enabled || !shouldFetchImmediately) {
      setIsLoading(false);
      return;
    }

    const controller = new AbortController();

    setIsLoading(initialData === undefined);
    setError(null);

    executeRequest<TData, TBody>(path, method, headers, body, timeout, controller.signal)
      .then((result) => {
        setData(result);
      })
      .catch((err) => {
        // Don't set error state for aborted requests
        if (err.name !== "AbortError") {
          setError(sanitizeError(err));
        }
      })
      .finally(() => {
        setIsLoading(false);
      });

    return () => {
      controller.abort(); // Cancel in-flight request
    };
    // Using headersKey and bodyKey instead of headers/body to prevent unnecessary re-fetches
    // when object references change but content remains the same
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, method, enabled, shouldFetchImmediately, initialData, headersKey, bodyKey, timeout]);

  const refetch = useCallback(() => execute(), [execute]);

  return {
    data,
    error,
    isLoading,
    execute,
    refetch,
    setData,
  };
}
