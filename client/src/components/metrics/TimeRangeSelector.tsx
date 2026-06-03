import { useIntl } from "react-intl";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { TimeWindow } from "@/hooks/useMetrics";

interface TimeRangeSelectorProps {
  value: TimeWindow;
  onChange: (value: TimeWindow) => void;
}

export function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  const intl = useIntl();

  return (
    <Select value={value} onValueChange={(next) => onChange(next as TimeWindow)}>
      <SelectTrigger
        aria-label={intl.formatMessage({ id: "dashboard.timeRange.label" })}
        className="w-[160px]"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="hour">
          {intl.formatMessage({ id: "dashboard.timeRange.hour" })}
        </SelectItem>
        <SelectItem value="day">{intl.formatMessage({ id: "dashboard.timeRange.day" })}</SelectItem>
        <SelectItem value="week">
          {intl.formatMessage({ id: "dashboard.timeRange.week" })}
        </SelectItem>
      </SelectContent>
    </Select>
  );
}
