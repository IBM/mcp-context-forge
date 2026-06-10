import { X } from "lucide-react";
import type { Toast } from "@/hooks/useToast";

interface ToastProps {
  toast: Toast;
  onDismiss: (id: string) => void;
}

export function ToastComponent({ toast, onDismiss }: ToastProps) {
  const bgColor = {
    success: "bg-green-500",
    error: "bg-red-500",
    info: "bg-blue-500",
    warning: "bg-yellow-500",
  }[toast.type];

  const ariaLive = toast.type === "error" || toast.type === "warning" ? "assertive" : "polite";

  return (
    <div
      className={`${bgColor} text-white px-4 py-3 rounded-lg shadow-lg flex items-center justify-between min-w-[300px] max-w-[500px]`}
      role="alert"
      aria-live={ariaLive}
      aria-atomic="true"
    >
      <span id={`toast-message-${toast.id}`}>{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="ml-4 hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-current rounded"
        aria-label={`Dismiss notification: ${toast.message}`}
        aria-describedby={`toast-message-${toast.id}`}
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastComponent key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
