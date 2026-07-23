import { useMemo, useState } from "react";

import { useDebouncedValue } from "./useDebouncedValue";

/** Debounced client-side search over an in-memory list; pass a memoised `getText`. */
export function useLocalSearch<T>(items: T[], getText: (item: T) => string, delayMs = 300) {
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query.trim().toLowerCase(), delayMs);

  const results = useMemo(() => {
    if (!debouncedQuery) {
      return items;
    }
    return items.filter((item) => getText(item).toLowerCase().includes(debouncedQuery));
  }, [items, getText, debouncedQuery]);

  return { query, setQuery, results };
}
