import { useCallback, useRef, useState } from "react";

/**
 * Track an element's rendered content-box width via ResizeObserver, for
 * container-width-driven responsive layout (as opposed to viewport-driven, like
 * `useIsMobile`). Returns a callback ref to attach and the current width in px.
 *
 * A callback ref (not a ref object + effect) is used deliberately: the measured
 * element often mounts *after* the first render — e.g. behind a loading/empty
 * early-return — and a callback ref fires exactly when the node attaches, so the
 * first measurement and the observer are set up at the right moment. A one-shot
 * `useEffect([])` would run before that node exists and never re-measure.
 *
 * Width is 0 until the ref attaches (first render, and in jsdom where the
 * observer is a no-op) — callers should treat 0 as "assume the narrow shape".
 */
export function useElementWidth<T extends HTMLElement>() {
  const [width, setWidth] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;

    if (!node) return;

    setWidth(node.clientWidth);

    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width;
      if (measured != null) {
        setWidth(measured);
      }
    });
    observer.observe(node);
    observerRef.current = observer;
  }, []);

  return [ref, width] as const;
}
