import { useIntl } from "react-intl";
import { MainNavIcon } from "../components/icons/MainNavIcon";

export function Loading() {
  const intl = useIntl();
  const label = intl.formatMessage({ id: "common.loading" });

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6">
        <div className="relative flex size-24 items-center justify-center">
          <div className="absolute inset-0 rounded-full border border-border" />
          <div className="absolute inset-2 rounded-full border border-neutral-200 dark:border-neutral-800" />
          <MainNavIcon className="relative h-12 w-14 text-foreground" />
        </div>

        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground"
        >
          <span>{label}</span>
          <span className="flex w-8 items-center gap-1" aria-hidden="true">
            <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.2s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.1s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-current" />
          </span>
        </div>
      </div>
    </main>
  );
}
