import { useState, useCallback, useRef, useEffect } from "react";

export type ToastType = "success" | "error" | "info" | "warning";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counterRef = useRef(0);
  const timeoutRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    const timeouts = timeoutRefs.current;
    return () => {
      timeouts.forEach((id) => clearTimeout(id));
      timeouts.clear();
    };
  }, []);

  const showToast = useCallback((type: ToastType, message: string, duration = 5000) => {
    const id = `toast-${++counterRef.current}`;
    const toast: Toast = { id, type, message, duration };

    setToasts((prev) => [...prev, toast]);

    if (duration > 0) {
      const timeoutId = setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        timeoutRefs.current.delete(id);
      }, duration);
      timeoutRefs.current.set(id, timeoutId);
    }

    return id;
  }, []);

  const dismissToast = useCallback((id: string) => {
    const timeoutId = timeoutRefs.current.get(id);
    if (timeoutId !== undefined) {
      clearTimeout(timeoutId);
      timeoutRefs.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return {
    toasts,
    showToast,
    dismissToast,
    success: (message: string, duration?: number) => showToast("success", message, duration),
    error: (message: string, duration?: number) => showToast("error", message, duration),
    info: (message: string, duration?: number) => showToast("info", message, duration),
    warning: (message: string, duration?: number) => showToast("warning", message, duration),
  };
}
