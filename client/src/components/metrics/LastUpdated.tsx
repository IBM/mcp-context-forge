import { useEffect, useState } from "react";
import { useIntl } from "react-intl";

interface LastUpdatedProps {
  /** Time the data was last fetched successfully, or null if never. */
  value: Date | null;
}

const TICK_MS = 10_000;
const JUST_NOW_THRESHOLD_MS = 10_000;

export function LastUpdated({ value }: LastUpdatedProps) {
  const intl = useIntl();
  // Tick state forces a re-render every TICK_MS so the relative label stays fresh
  // even while no parent re-render happens.
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = globalThis.setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => globalThis.clearInterval(id);
  }, []);

  if (!value) {
    return (
      <span className="text-xs text-muted-foreground">
        {intl.formatMessage({ id: "dashboard.lastUpdated.never" })}
      </span>
    );
  }

  const ageMs = Date.now() - value.getTime();
  let label: string;

  if (ageMs < JUST_NOW_THRESHOLD_MS) {
    label = intl.formatMessage({ id: "dashboard.lastUpdated.justNow" });
  } else if (ageMs < 60 * 60 * 1000) {
    const minutes = Math.max(1, Math.floor(ageMs / 60_000));
    label = intl.formatMessage({ id: "dashboard.lastUpdated.minutes" }, { minutes });
  } else {
    const hours = Math.floor(ageMs / (60 * 60 * 1000));
    label = intl.formatMessage({ id: "dashboard.lastUpdated.hours" }, { hours });
  }

  return (
    <span className="text-xs text-muted-foreground" title={value.toISOString()}>
      {label}
    </span>
  );
}
