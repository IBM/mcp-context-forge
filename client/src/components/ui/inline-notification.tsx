import { CircleCheck, CircleAlert, X } from "lucide-react";

interface InlineNotificationProps {
  type: "success" | "error";
  message: string;
  onDismiss?: () => void;
  dismissLabel?: string;
}

export function InlineNotification({
  type,
  message,
  onDismiss,
  dismissLabel = "Dismiss notification",
}: InlineNotificationProps) {
  const isSuccess = type === "success";

  return (
    <div
      role={isSuccess ? "status" : "alert"}
      className="flex items-center justify-between rounded-md border border-neutral-200 bg-background p-3 dark:border-neutral-800"
    >
      <div className="flex items-center gap-2">
        {isSuccess ? (
          <CircleCheck className="h-4 w-4 shrink-0 text-green-500" aria-hidden="true" />
        ) : (
          <CircleAlert className="h-4 w-4 shrink-0 text-red-500" aria-hidden="true" />
        )}
        <p className={`text-sm ${isSuccess ? "text-green-500" : "text-red-600 dark:text-red-400"}`}>
          {message}
        </p>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={dismissLabel}
          className="ml-2 shrink-0 p-1 opacity-60 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
