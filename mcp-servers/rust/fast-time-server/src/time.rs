// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

#[cfg(test)]
use chrono::Offset;
use chrono::{DateTime, FixedOffset, SecondsFormat, TimeZone, Utc};
use chrono_tz::Tz;

#[derive(Debug, Clone, Copy)]
pub(crate) enum ParsedTimezone {
    Fixed(FixedOffset),
    Named(Tz),
}

impl ParsedTimezone {
    pub(crate) fn format_utc(self, utc: DateTime<Utc>) -> String {
        match self {
            Self::Fixed(offset) if offset.local_minus_utc() == 0 => {
                utc.to_rfc3339_opts(SecondsFormat::Secs, true)
            }
            Self::Fixed(offset) => utc.with_timezone(&offset).to_rfc3339(),
            Self::Named(tz) => utc.with_timezone(&tz).to_rfc3339(),
        }
    }

    /// Format an instant in this zone using a chrono `strftime` pattern
    /// (e.g. `"%Y-%m-%d %H:%M:%S %Z"`). `%Z` yields the zone abbreviation for
    /// named zones and the numeric offset for fixed offsets.
    pub(crate) fn format_local(self, utc: DateTime<Utc>, fmt: &str) -> String {
        match self {
            Self::Fixed(offset) => utc.with_timezone(&offset).format(fmt).to_string(),
            Self::Named(tz) => utc.with_timezone(&tz).format(fmt).to_string(),
        }
    }

    fn local_datetime_to_utc(self, naive: &chrono::NaiveDateTime) -> Option<DateTime<Utc>> {
        match self {
            Self::Fixed(offset) => offset
                .from_local_datetime(naive)
                .single()
                .map(|dt| dt.with_timezone(&Utc)),
            Self::Named(tz) => tz
                .from_local_datetime(naive)
                .single()
                .map(|dt| dt.with_timezone(&Utc)),
        }
    }

    #[cfg(test)]
    fn offset_seconds_at(self, utc: DateTime<Utc>) -> i32 {
        match self {
            Self::Fixed(offset) => offset.local_minus_utc(),
            Self::Named(tz) => utc.with_timezone(&tz).offset().fix().local_minus_utc(),
        }
    }
}

/// Parse an IANA timezone name or fixed UTC offset.
pub(crate) fn parse_timezone(tz: &str) -> Result<ParsedTimezone, String> {
    if tz.eq_ignore_ascii_case("UTC") || tz.eq_ignore_ascii_case("GMT") {
        return Ok(ParsedTimezone::Fixed(FixedOffset::east_opt(0).unwrap()));
    }

    if tz.starts_with('+') || tz.starts_with('-') {
        return parse_offset(tz).map(ParsedTimezone::Fixed);
    }

    tz.parse::<Tz>()
        .map(ParsedTimezone::Named)
        .map_err(|_| format!("Unknown timezone: {}", tz))
}

/// Parse an input time string in the given offset, accepting RFC3339 and a
/// handful of common formats used by the Go fast-time-server port.
pub(crate) fn parse_time_in_timezone(
    time_str: &str,
    timezone: &ParsedTimezone,
) -> Result<DateTime<Utc>, String> {
    if let Ok(parsed) = DateTime::parse_from_rfc3339(time_str) {
        return Ok(parsed.with_timezone(&Utc));
    }
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"] {
        if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(time_str, fmt)
            && let Some(dt) = timezone.local_datetime_to_utc(&naive)
        {
            return Ok(dt);
        }
        if let Ok(date) = chrono::NaiveDate::parse_from_str(time_str, fmt)
            && let Some(naive) = date.and_hms_opt(0, 0, 0)
            && let Some(dt) = timezone.local_datetime_to_utc(&naive)
        {
            return Ok(dt);
        }
    }
    Err(format!("unrecognized time format: {}", time_str))
}

/// Parse an offset string like "+05:30" or "-08:00".
fn parse_offset(s: &str) -> Result<FixedOffset, String> {
    let (sign, rest) = if let Some(stripped) = s.strip_prefix('+') {
        (1, stripped)
    } else if let Some(stripped) = s.strip_prefix('-') {
        (-1, stripped)
    } else {
        return Err("Offset must start with + or -".to_string());
    };

    let parts: Vec<&str> = rest.split(':').collect();
    if parts.len() != 2 {
        return Err("Offset must be in format +HH:MM or -HH:MM".to_string());
    }

    let hours: i32 = parts[0].parse().map_err(|_| "Invalid hours in offset")?;
    let minutes: i32 = parts[1].parse().map_err(|_| "Invalid minutes in offset")?;

    let total_seconds = sign * (hours * 3600 + minutes * 60);

    FixedOffset::east_opt(total_seconds).ok_or_else(|| format!("Offset out of range: {}", s))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_utc() {
        let timezone = parse_timezone("UTC").unwrap();
        let utc = DateTime::parse_from_rfc3339("2025-06-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(timezone.offset_seconds_at(utc), 0);
    }

    #[test]
    fn test_parse_gmt() {
        let timezone = parse_timezone("GMT").unwrap();
        let utc = DateTime::parse_from_rfc3339("2025-06-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(timezone.offset_seconds_at(utc), 0);
    }

    #[test]
    fn test_parse_dublin() {
        let timezone = parse_timezone("Europe/Dublin").unwrap();
        let utc = DateTime::parse_from_rfc3339("2025-01-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(timezone.offset_seconds_at(utc), 0);
    }

    #[test]
    fn test_parse_new_york() {
        let timezone = parse_timezone("America/New_York").unwrap();
        let summer = DateTime::parse_from_rfc3339("2025-06-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let winter = DateTime::parse_from_rfc3339("2025-01-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(timezone.offset_seconds_at(summer), -4 * 3600);
        assert_eq!(timezone.offset_seconds_at(winter), -5 * 3600);
    }

    #[test]
    fn test_parse_tokyo() {
        let timezone = parse_timezone("Asia/Tokyo").unwrap();
        let utc = DateTime::parse_from_rfc3339("2025-06-21T16:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(timezone.offset_seconds_at(utc), 9 * 3600);
    }

    #[test]
    fn test_parse_fixed_offset_positive() {
        let offset = parse_offset("+05:30").unwrap();
        assert_eq!(offset.local_minus_utc(), 5 * 3600 + 30 * 60);
    }

    #[test]
    fn test_parse_fixed_offset_negative() {
        let offset = parse_offset("-08:00").unwrap();
        assert_eq!(offset.local_minus_utc(), -8 * 3600);
    }

    #[test]
    fn test_unknown_timezone() {
        let result = parse_timezone("Invalid/Timezone");
        assert!(result.is_err());
    }
}
