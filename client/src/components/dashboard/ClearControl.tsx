/**
 * ClearControl — returns the home to its default state.
 *
 * Present in the main content area of every non-default state. Navigates to
 * `/app/` (dropping the `?view=` param).
 */

import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { useRouter } from "@/router";
import { viewHref } from "./homeStates";

export function ClearControl({ className }: { className?: string }) {
  const intl = useIntl();
  const { navigate } = useRouter();

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={() => navigate(viewHref("default"))}
    >
      {intl.formatMessage({ id: "dashboard.home.clear" })}
    </Button>
  );
}
