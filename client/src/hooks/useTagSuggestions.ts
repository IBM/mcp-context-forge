import { useEffect, useState } from "react";
import { api } from "@/api/client";

interface TagInfoName {
  name: string;
}

let cache: string[] | null = null;

/**
 * Tag names from `GET /tags`, for autocomplete. Cached module-wide so the
 * suggestion list is fetched once per session. Autocomplete is best-effort: a
 * failed fetch just yields no suggestions and never blocks tag entry.
 */
export function useTagSuggestions(enabled = true): string[] {
  const [tags, setTags] = useState<string[]>(cache ?? []);

  useEffect(() => {
    if (!enabled || cache) return;
    let cancelled = false;
    api
      .get<TagInfoName[]>("/tags")
      .then((response) => {
        cache = (Array.isArray(response) ? response : []).map((tag) => tag.name).filter(Boolean);
        if (!cancelled) setTags(cache);
      })
      .catch(() => {
        // ponytail: suggestions are best-effort; a failed /tags fetch just means no autocomplete.
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return tags;
}
