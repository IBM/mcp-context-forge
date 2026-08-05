/**
 * ActivityFeedButton — default-state entry point into the activity feed view.
 * Navigates to `/app/?view=activity`.
 */

import { List } from "lucide-react";
import { useIntl } from "react-intl";

import { Button } from "@/components/ui/button";
import { useRouter } from "@/router";
import { viewHref } from "./homeStates";

export function ActivityFeedButton({ className }: { className?: string }) {
  const intl = useIntl();
  const { navigate } = useRouter();

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={() => navigate(viewHref("activity"))}
    >
      <List />
      {intl.formatMessage({ id: "dashboard.home.card.activity" })}
    </Button>
  );
}
