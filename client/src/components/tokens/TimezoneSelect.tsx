import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface TimezoneOption {
  /** IANA identifier submitted to the backend (validated against IANA there). */
  value: string;
  /** Friendly label shown in the dropdown. */
  label: string;
}

interface TimezoneRegion {
  region: string;
  zones: TimezoneOption[];
}

// Curated set of common timezones (à la the shadcn scrollable Select example),
// grouped into broad regions. Values are real IANA identifiers so they satisfy
// the backend's timezone validation; labels are the familiar abbreviations.
const TIMEZONE_REGIONS: TimezoneRegion[] = [
  {
    region: "Universal",
    zones: [{ value: "UTC", label: "Coordinated Universal Time (UTC)" }],
  },
  {
    region: "North America",
    zones: [
      { value: "America/New_York", label: "Eastern Standard Time (EST)" },
      { value: "America/Chicago", label: "Central Standard Time (CST)" },
      { value: "America/Denver", label: "Mountain Standard Time (MST)" },
      { value: "America/Los_Angeles", label: "Pacific Standard Time (PST)" },
      { value: "America/Anchorage", label: "Alaska Standard Time (AKST)" },
      { value: "Pacific/Honolulu", label: "Hawaii Standard Time (HST)" },
    ],
  },
  {
    region: "Europe & Africa",
    zones: [
      { value: "Europe/London", label: "Greenwich Mean Time (GMT)" },
      { value: "Europe/Paris", label: "Central European Time (CET)" },
      { value: "Europe/Helsinki", label: "Eastern European Time (EET)" },
      { value: "Europe/Lisbon", label: "Western European Time (WET)" },
      { value: "Africa/Maputo", label: "Central Africa Time (CAT)" },
      { value: "Africa/Nairobi", label: "East Africa Time (EAT)" },
    ],
  },
  {
    region: "Asia",
    zones: [
      { value: "Europe/Moscow", label: "Moscow Time (MSK)" },
      { value: "Asia/Kolkata", label: "India Standard Time (IST)" },
      { value: "Asia/Shanghai", label: "China Standard Time (CST)" },
      { value: "Asia/Tokyo", label: "Japan Standard Time (JST)" },
      { value: "Asia/Seoul", label: "Korea Standard Time (KST)" },
      { value: "Asia/Makassar", label: "Indonesia Central Standard Time (WITA)" },
    ],
  },
  {
    region: "Australia & Pacific",
    zones: [
      { value: "Australia/Perth", label: "Australian Western Standard Time (AWST)" },
      { value: "Australia/Adelaide", label: "Australian Central Standard Time (ACST)" },
      { value: "Australia/Sydney", label: "Australian Eastern Standard Time (AEST)" },
      { value: "Pacific/Auckland", label: "New Zealand Standard Time (NZST)" },
      { value: "Pacific/Fiji", label: "Fiji Time (FJT)" },
    ],
  },
  {
    region: "South America",
    zones: [
      { value: "America/Argentina/Buenos_Aires", label: "Argentina Time (ART)" },
      { value: "America/La_Paz", label: "Bolivia Time (BOT)" },
      { value: "America/Sao_Paulo", label: "Brasília Time (BRT)" },
      { value: "America/Santiago", label: "Chile Standard Time (CLT)" },
    ],
  },
];

interface TimezoneSelectProps {
  id?: string;
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  /** Classes applied to the trigger, so callers can match sibling field styling. */
  triggerClassName?: string;
}

/**
 * Grouped, scrollable timezone picker composed from the shared Select primitives
 * (no new UI primitive), mirroring the shadcn scrollable Select example: a
 * curated shortlist of common zones grouped by region, with real IANA values.
 */
export function TimezoneSelect({
  id,
  value,
  onValueChange,
  placeholder,
  triggerClassName,
}: TimezoneSelectProps) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger id={id} className={triggerClassName}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-72">
        {TIMEZONE_REGIONS.map(({ region, zones }) => (
          <SelectGroup key={region}>
            <SelectLabel>{region}</SelectLabel>
            {zones.map((zone) => (
              <SelectItem key={zone.value} value={zone.value}>
                {zone.label}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}
