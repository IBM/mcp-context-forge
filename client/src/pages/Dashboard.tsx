import { useIntl } from "react-intl";

export function Dashboard() {
  const intl = useIntl();

  return (
    <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
      {intl.formatMessage({ id: "dashboard.title" })}
    </h1>
  );
}
