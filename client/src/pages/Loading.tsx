import { useIntl } from "react-intl";
import { MainNavIcon } from "../components/icons/MainNavIcon";

export function Loading() {
  const intl = useIntl();
  const label = intl.formatMessage({ id: "common.loading" });

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen items-center justify-center px-6">
        <div
          role="status"
          aria-live="polite"
          aria-label={label}
          className="flex size-24 items-center justify-center rounded-lg border border-border bg-card text-card-foreground shadow-sm"
        >
          <MainNavIcon className="h-12 w-14" />
        </div>
      </div>
    </main>
  );
}
