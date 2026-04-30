import { useIntl } from "react-intl";

export function RestApi() {
  const intl = useIntl();

  return (
    <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
      {intl.formatMessage({ id: "restApi.title" })}
    </h1>
  );
}
