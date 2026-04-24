import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";

type QueryMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface UseQueryOptions<TData, TBody = unknown> {
  method?: QueryMethod;
  enabled?: boolean;
  immediate?: boolean;
  initialData?: TData;
  body?: TBody;
  headers?: Record<string, string>;
}

interface UseQueryResult<TData, TBody = unknown> {
  data: TData | undefined;
  error: unknown;
  isLoading: boolean;
  execute: (overrideBody?: TBody) => Promise<TData>;
  refetch: () => Promise<TData>;
}

function createHeadersKey(headers?: Record<string, string>): string {
  if (!headers) return "";
  return JSON.stringify(
    Object.entries(headers).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function createBodyKey(body: unknown): string {
  if (body === undefined) return "";
  return JSON.stringify(body);
}

async function executeRequest<TData, TBody>(
  path: string,
  method: QueryMethod,
  headers?: Record<string, string>,
  body?: TBody,
): Promise<TData> {
  switch (method) {
    case "GET":
      return api.get<TData>(path, headers);
    case "POST":
      return api.post<TData>(path, body, { headers });
    case "PUT":
      return api.put<TData>(path, body, { headers });
    case "PATCH":
      return api.patch<TData>(path, body, { headers });
    case "DELETE":
      return api.delete<TData>(path, { headers });
  }
}

export function useQuery<TData, TBody = unknown>(
  path: string,
  {
    method = "GET",
    enabled = true,
    immediate,
    initialData,
    body,
    headers,
  }: UseQueryOptions<TData, TBody> = {},
): UseQueryResult<TData, TBody> {
  const shouldFetchImmediately = immediate ?? method === "GET";
  const [data, setData] = useState<TData | undefined>(initialData);
  const [error, setError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState<boolean>(
    enabled && shouldFetchImmediately && initialData === undefined,
  );

  const headersKey = useMemo(() => createHeadersKey(headers), [headers]);
  const bodyKey = useMemo(() => createBodyKey(body), [body]);

  const execute = useCallback(
    async (overrideBody?: TBody): Promise<TData> => {
      setIsLoading(true);
      setError(null);

      try {
        const result = await executeRequest<TData, TBody>(
          path,
          method,
          headers,
          overrideBody === undefined ? body : overrideBody,
        );
        setData(result);
        return result;
      } catch (err) {
        setError(err);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [path, method, headers, body],
  );

  useEffect(() => {
    if (!enabled || !shouldFetchImmediately) {
      setIsLoading(false);
      return;
    }

    let active = true;

    setIsLoading(initialData === undefined);
    setError(null);

    executeRequest<TData, TBody>(path, method, headers, body)
      .then((result) => {
        if (!active) return;
        setData(result);
      })
      .catch((err) => {
        if (!active) return;
        setError(err);
      })
      .finally(() => {
        if (!active) return;
        setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [
    path,
    method,
    headers,
    body,
    enabled,
    shouldFetchImmediately,
    initialData,
    headersKey,
    bodyKey,
  ]);

  return {
    data,
    error,
    isLoading,
    execute,
    refetch: () => execute(),
  };
}
