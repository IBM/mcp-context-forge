import { useIntl } from "react-intl";

import { RecentActivity } from "@/components/dashboard/RecentActivity";

export function Dashboard() {
  const intl = useIntl();

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <h1 className="sr-only">{intl.formatMessage({ id: "dashboard.title" })}</h1>
      <RecentActivity />
      <aside aria-label="Dashboard sidebar" />
    </div>
  );
}
