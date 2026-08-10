import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { useIntl } from "react-intl";

import { BackButton } from "@/components/ui/back-button";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useQuery } from "@/hooks/useQuery";
import { tokensApi } from "@/api/tokens";
import { parseApiError } from "@/lib/errorUtils";
import type { TeamsResponse } from "@/types/team";
import type { PermissionListResponse } from "@/generated/types/permissionListResponse";
import type { TokenScopeRequestTimeRestrictions } from "@/generated/types/tokenScopeRequestTimeRestrictions";
import type { TokenScopeRequestUsageLimits } from "@/generated/types/tokenScopeRequestUsageLimits";
import type { TokenCreateRequest, TokenResponse, TokenScopeRequest } from "@/types/token";
import { TimezoneSelect } from "./TimezoneSelect";
import { TokenIcon } from "./TokenIcon";
import {
  availableBuckets,
  bucketScopes,
  PERMISSION_BUCKET_ORDER,
  selectedScopes,
  type PermissionBucket,
} from "./tokenScopes";

const EXPIRY_OPTIONS = [7, 30, 60, 90, 365] as const;
const DEFAULT_EXPIRY_DAYS = 30;

const FIELD_CONTROL_CLASS =
  "h-10 border-neutral-300 shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0 dark:border-neutral-700";

// Full day names match the backend `time_restrictions.days` contract (VALID_DAYS);
// the display label is localized, the submitted value stays English.
const WEEKDAYS = [
  { value: "Monday", key: "monday" },
  { value: "Tuesday", key: "tuesday" },
  { value: "Wednesday", key: "wednesday" },
  { value: "Thursday", key: "thursday" },
  { value: "Friday", key: "friday" },
  { value: "Saturday", key: "saturday" },
  { value: "Sunday", key: "sunday" },
] as const;
const ALL_DAYS = WEEKDAYS.map((day) => day.value);

// "HH:MM" options for the allowed-hours window (hourly).
const HOUR_OPTIONS = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, "0")}:00`);

type ScopeMode = "all" | "selected";

interface TokenFormProps {
  onCancel: () => void;
  /** Called after a successful create with the one-time secret and the token record. */
  onCreated: (accessToken: string, token: TokenResponse) => void;
}

interface FieldProps {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  children: ReactNode;
}

function Field({ id, label, required, error, children }: FieldProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id} className="text-sm font-medium text-neutral-950 dark:text-white">
        {label}
        {required && (
          <>
            {" "}
            <span className="text-red-500" aria-hidden="true">
              *
            </span>
            <span className="sr-only">(required)</span>
          </>
        )}
      </Label>
      {children}
      {error && (
        <p id={`${id}-error`} className="text-sm text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function TokenForm({ onCancel, onCreated }: TokenFormProps) {
  const intl = useIntl();

  const [name, setName] = useState("");
  const [teamId, setTeamId] = useState("");
  const [expiryDays, setExpiryDays] = useState<number>(DEFAULT_EXPIRY_DAYS);
  const [mode, setMode] = useState<ScopeMode>("all");
  const [selectedBuckets, setSelectedBuckets] = useState<PermissionBucket[]>([]);
  const [description, setDescription] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [serverId, setServerId] = useState("");
  const [ipRestrictions, setIpRestrictions] = useState("");
  const [requestsPerHour, setRequestsPerHour] = useState("");
  const [requestsPerDay, setRequestsPerDay] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [timezone, setTimezone] = useState("");
  const [allowedDays, setAllowedDays] = useState<string[]>([...ALL_DAYS]);
  const [errors, setErrors] = useState<{ name?: string; permissions?: string; submit?: string }>(
    {},
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: teamsData } = useQuery<TeamsResponse>("/teams");
  const teams = useMemo(() => teamsData?.teams ?? [], [teamsData?.teams]);
  const showTeamSelector = teams.length > 1;

  // Resolve the team the token is scoped to. With a single team we submit that
  // team's id (never null — a null team_id silently yields a public-only token
  // for multi-team users). With several, the user picks explicitly.
  const effectiveTeamId = showTeamSelector ? teamId : teams[0]?.id;

  // Default the selector to the first team once the list loads.
  useEffect(() => {
    if (showTeamSelector && !teamId && teams[0]) {
      setTeamId(teams[0].id);
    }
  }, [showTeamSelector, teamId, teams]);

  // The full permission catalog is the universe of selectable scopes; it comes
  // from the backend (never hardcoded) and is team-independent.
  const { data: catalogData, isLoading: catalogLoading } = useQuery<PermissionListResponse>(
    "/rbac/permissions/available",
    { enabled: mode === "selected" },
  );
  const catalog = useMemo(() => catalogData?.all_permissions ?? [], [catalogData?.all_permissions]);

  // Caller's grantable permissions for the selected team; intersected with the
  // catalog to drive the buckets, re-filtering whenever the team changes (#6032).
  const permsPath =
    mode === "selected"
      ? `/rbac/my/permissions${effectiveTeamId ? `?team_id=${encodeURIComponent(effectiveTeamId)}` : ""}`
      : null;
  const { data: permsData, isLoading: permsLoading } = useQuery<string[]>(permsPath, {
    enabled: mode === "selected" && permsPath !== null,
  });
  const callerPermissions = useMemo(() => permsData ?? [], [permsData]);

  // Either request in flight; used to show a spinner instead of the empty-state
  // message while the grantable scopes are still loading.
  const permissionsLoading = catalogLoading || permsLoading;
  const buckets = useMemo(
    () => availableBuckets(catalog, callerPermissions),
    [catalog, callerPermissions],
  );

  // Drop any selected bucket that is no longer grantable after a team switch.
  useEffect(() => {
    setSelectedBuckets((prev) => prev.filter((bucket) => buckets.includes(bucket)));
  }, [buckets]);

  const toggleBucket = (bucket: PermissionBucket, checked: boolean) => {
    setSelectedBuckets((prev) =>
      checked ? [...prev, bucket] : prev.filter((item) => item !== bucket),
    );
    setErrors((prev) => ({ ...prev, permissions: undefined }));
  };

  const toggleDay = (day: string, checked: boolean) => {
    setAllowedDays((prev) => (checked ? [...prev, day] : prev.filter((item) => item !== day)));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const nextErrors: typeof errors = {};
    if (!name.trim()) {
      nextErrors.name = intl.formatMessage({ id: "tokens.form.name.required" });
    }

    const chosenScopes = selectedScopes(selectedBuckets, catalog, callerPermissions);
    if (mode === "selected" && chosenScopes.length === 0) {
      nextErrors.permissions = intl.formatMessage({ id: "tokens.form.permissions.required" });
    }

    if (nextErrors.name || nextErrors.permissions) {
      setErrors(nextErrors);
      return;
    }

    // Build the optional scope object. "All available" omits permissions so the
    // token inherits the caller's own permissions at request time — we never send
    // "*" (rejected for non-admins). Advanced narrowing (server / IP) still layers
    // on top of either mode.
    const scope: TokenScopeRequest = {};
    if (mode === "selected") {
      scope.permissions = chosenScopes;
    }
    if (serverId.trim()) {
      scope.server_id = serverId.trim();
    }
    const ipList = ipRestrictions
      .split(/[\n,]/)
      .map((entry) => entry.trim())
      .filter(Boolean);
    if (ipList.length > 0) {
      scope.ip_restrictions = ipList;
    }

    // Rate limits (usage_limits): only positive integers are sent.
    const usageLimits: TokenScopeRequestUsageLimits = {};
    const perHour = Number.parseInt(requestsPerHour, 10);
    if (Number.isFinite(perHour) && perHour > 0) {
      usageLimits.requests_per_hour = perHour;
    }
    const perDay = Number.parseInt(requestsPerDay, 10);
    if (Number.isFinite(perDay) && perDay > 0) {
      usageLimits.requests_per_day = perDay;
    }
    if (Object.keys(usageLimits).length > 0) {
      scope.usage_limits = usageLimits;
    }

    // Time restrictions: an hour window and/or a day subset. All seven days
    // selected means "no day restriction", so it is omitted.
    const timeRestrictions: TokenScopeRequestTimeRestrictions = {};
    const hasWindow = Boolean(startTime || endTime);
    const daysRestricted = allowedDays.length > 0 && allowedDays.length < ALL_DAYS.length;
    if (startTime) {
      timeRestrictions.start_time = startTime;
    }
    if (endTime) {
      timeRestrictions.end_time = endTime;
    }
    if (hasWindow && timezone) {
      timeRestrictions.timezone = timezone;
    }
    if (daysRestricted) {
      timeRestrictions.days = allowedDays;
    }
    if (Object.keys(timeRestrictions).length > 0) {
      scope.time_restrictions = timeRestrictions;
    }

    const payload: TokenCreateRequest = {
      name: name.trim(),
      expires_in_days: expiryDays,
      description: description.trim() || undefined,
      team_id: effectiveTeamId,
    };
    if (Object.keys(scope).length > 0) {
      payload.scope = scope;
    }

    setErrors({});
    setIsSubmitting(true);
    try {
      const response = await tokensApi.create(payload);
      onCreated(response.access_token, response.token);
    } catch (err) {
      setErrors({
        submit: parseApiError(err, intl.formatMessage({ id: "tokens.form.error.generic" })),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <BackButton onClick={onCancel} />

      <div className="rounded-xl border border-neutral-200 bg-inherit shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <TokenIcon />
              <h2
                id="token-form-title"
                className="align-middle text-base font-semibold leading-6 tracking-normal text-neutral-950 dark:text-neutral-50"
              >
                {intl.formatMessage({ id: "tokens.form.title" })}
              </h2>
            </div>
            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "tokens.form.subtitle" })}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5" aria-labelledby="token-form-title">
            <Field
              id="token-name"
              label={intl.formatMessage({ id: "tokens.form.name" })}
              required
              error={errors.name}
            >
              <Input
                id="token-name"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setErrors((prev) => ({ ...prev, name: undefined }));
                }}
                placeholder={intl.formatMessage({ id: "tokens.form.name.placeholder" })}
                className={FIELD_CONTROL_CLASS}
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "token-name-error" : undefined}
              />
            </Field>

            {showTeamSelector && (
              <Field
                id="token-team"
                label={intl.formatMessage({ id: "tokens.form.team" })}
                required
              >
                <Select value={teamId} onValueChange={setTeamId}>
                  <SelectTrigger id="token-team" className={`w-full ${FIELD_CONTROL_CLASS}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {teams.map((team) => (
                      <SelectItem key={team.id} value={team.id}>
                        {team.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}

            <Field
              id="token-expiry"
              label={intl.formatMessage({ id: "tokens.form.expiration" })}
              required
            >
              <Select
                value={String(expiryDays)}
                onValueChange={(value) => setExpiryDays(Number(value))}
              >
                <SelectTrigger id="token-expiry" className={`w-full ${FIELD_CONTROL_CLASS}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPIRY_OPTIONS.map((days) => (
                    <SelectItem key={days} value={String(days)}>
                      {intl.formatMessage({ id: "tokens.form.expiration.days" }, { days })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <div className="space-y-3">
              <p className="text-sm font-medium text-neutral-950 dark:text-white">
                {intl.formatMessage({ id: "tokens.form.permissions" })}
              </p>
              <RadioGroup
                value={mode}
                onValueChange={(value) => {
                  setMode(value as ScopeMode);
                  setErrors((prev) => ({ ...prev, permissions: undefined }));
                }}
              >
                <div className="flex items-center gap-2">
                  <RadioGroupItem value="all" id="token-scope-all" />
                  <Label
                    htmlFor="token-scope-all"
                    className="text-sm text-neutral-950 dark:text-white"
                  >
                    {intl.formatMessage({ id: "tokens.form.permissions.all" })}
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <RadioGroupItem value="selected" id="token-scope-selected" />
                  <Label
                    htmlFor="token-scope-selected"
                    className="text-sm text-neutral-950 dark:text-white"
                  >
                    {intl.formatMessage({ id: "tokens.form.permissions.selected" })}
                  </Label>
                </div>
              </RadioGroup>

              {mode === "selected" && (
                <div className="space-y-3 p-4">
                  {permissionsLoading ? (
                    <div className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400">
                      {intl.formatMessage({ id: "tokens.form.permissions.loading" })}
                    </div>
                  ) : buckets.length === 0 ? (
                    <p className="text-sm text-neutral-600 dark:text-neutral-400">
                      {intl.formatMessage({ id: "tokens.form.permissions.none" })}
                    </p>
                  ) : (
                    <>
                      {PERMISSION_BUCKET_ORDER.filter((bucket) => buckets.includes(bucket)).map(
                        (bucket) => {
                          const scopes = bucketScopes(bucket, catalog, callerPermissions);
                          return (
                            <label
                              key={bucket}
                              htmlFor={`token-bucket-${bucket}`}
                              className="flex cursor-pointer items-start gap-3"
                            >
                              <Checkbox
                                id={`token-bucket-${bucket}`}
                                checked={selectedBuckets.includes(bucket)}
                                onCheckedChange={(value) => toggleBucket(bucket, value === true)}
                                className="mt-0.5"
                              />
                              <span className="w-16 shrink-0 text-sm text-neutral-950 dark:text-white">
                                {intl.formatMessage({ id: `tokens.form.bucket.${bucket}` })}
                              </span>
                              <span className="flex flex-1 flex-wrap gap-1.5">
                                {scopes.map((scope) => (
                                  <span
                                    key={scope}
                                    className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                                  >
                                    {scope}
                                  </span>
                                ))}
                              </span>
                            </label>
                          );
                        },
                      )}
                    </>
                  )}
                  {errors.permissions && (
                    <p className="text-sm text-red-600 dark:text-red-400" role="alert">
                      {errors.permissions}
                    </p>
                  )}
                </div>
              )}
            </div>

            <Field
              id="token-description"
              label={intl.formatMessage({ id: "tokens.form.description" })}
            >
              <Textarea
                id="token-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={intl.formatMessage({ id: "tokens.form.description.placeholder" })}
                rows={3}
                className="resize-none border-neutral-300 focus-visible:ring-1 focus-visible:ring-offset-0 dark:border-neutral-700"
              />
            </Field>

            <div className="flex flex-col gap-3">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-full items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-600 hover:text-neutral-950 dark:border-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300"
                aria-expanded={advancedOpen}
                aria-controls="token-advanced-region"
              >
                <ChevronDown
                  className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`}
                  aria-hidden="true"
                />
                {intl.formatMessage({ id: "tokens.form.advanced" })}
              </Button>

              {advancedOpen && (
                <div
                  id="token-advanced-region"
                  role="region"
                  aria-label={intl.formatMessage({ id: "tokens.form.advanced" })}
                  className="space-y-4"
                >
                  <Field
                    id="token-server-id"
                    label={intl.formatMessage({ id: "tokens.form.serverId" })}
                  >
                    <Input
                      id="token-server-id"
                      value={serverId}
                      onChange={(event) => setServerId(event.target.value)}
                      placeholder={intl.formatMessage({ id: "tokens.form.serverId.placeholder" })}
                      className={FIELD_CONTROL_CLASS}
                    />
                  </Field>

                  <Field
                    id="token-ip-restrictions"
                    label={intl.formatMessage({ id: "tokens.form.ipRestrictions" })}
                  >
                    <Input
                      id="token-ip-restrictions"
                      value={ipRestrictions}
                      onChange={(event) => setIpRestrictions(event.target.value)}
                      placeholder={intl.formatMessage({
                        id: "tokens.form.ipRestrictions.placeholder",
                      })}
                      className={FIELD_CONTROL_CLASS}
                    />
                  </Field>

                  <div className="space-y-1">
                    <p className="text-base font-medium text-neutral-950 dark:text-white">
                      {intl.formatMessage({ id: "tokens.form.rateLimits" })}
                    </p>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <Field
                        id="token-requests-per-hour"
                        label={intl.formatMessage({ id: "tokens.form.requestsPerHour" })}
                      >
                        <Input
                          id="token-requests-per-hour"
                          type="number"
                          min={1}
                          value={requestsPerHour}
                          onChange={(event) => setRequestsPerHour(event.target.value)}
                          placeholder={intl.formatMessage({
                            id: "tokens.form.requestsPerHour.placeholder",
                          })}
                          className={FIELD_CONTROL_CLASS}
                        />
                      </Field>
                      <Field
                        id="token-requests-per-day"
                        label={intl.formatMessage({ id: "tokens.form.requestsPerDay" })}
                      >
                        <Input
                          id="token-requests-per-day"
                          type="number"
                          min={1}
                          value={requestsPerDay}
                          onChange={(event) => setRequestsPerDay(event.target.value)}
                          placeholder={intl.formatMessage({
                            id: "tokens.form.requestsPerDay.placeholder",
                          })}
                          className={FIELD_CONTROL_CLASS}
                        />
                      </Field>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <p className="text-base font-medium text-neutral-950 dark:text-white">
                      {intl.formatMessage({ id: "tokens.form.allowedHours" })}
                    </p>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field
                        id="token-start-time"
                        label={intl.formatMessage({ id: "tokens.form.start" })}
                      >
                        <Select value={startTime} onValueChange={setStartTime}>
                          <SelectTrigger
                            id="token-start-time"
                            className={`w-full ${FIELD_CONTROL_CLASS}`}
                          >
                            <SelectValue
                              placeholder={intl.formatMessage({ id: "tokens.form.select" })}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {HOUR_OPTIONS.map((hour) => (
                              <SelectItem key={hour} value={hour}>
                                {hour}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </Field>
                      <Field
                        id="token-end-time"
                        label={intl.formatMessage({ id: "tokens.form.end" })}
                      >
                        <Select value={endTime} onValueChange={setEndTime}>
                          <SelectTrigger
                            id="token-end-time"
                            className={`w-full ${FIELD_CONTROL_CLASS}`}
                          >
                            <SelectValue
                              placeholder={intl.formatMessage({ id: "tokens.form.select" })}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {HOUR_OPTIONS.map((hour) => (
                              <SelectItem key={hour} value={hour}>
                                {hour}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </Field>
                      <Field
                        id="token-timezone"
                        label={intl.formatMessage({ id: "tokens.form.timezone" })}
                      >
                        <TimezoneSelect
                          id="token-timezone"
                          value={timezone}
                          onValueChange={setTimezone}
                          placeholder={intl.formatMessage({ id: "tokens.form.select" })}
                          triggerClassName={`w-full ${FIELD_CONTROL_CLASS}`}
                        />
                      </Field>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <p className="text-base font-medium text-neutral-950 dark:text-white">
                      {intl.formatMessage({ id: "tokens.form.allowedDays" })}
                    </p>
                    <div className="flex flex-wrap gap-x-4 gap-y-2">
                      {WEEKDAYS.map((day) => (
                        <label
                          key={day.value}
                          htmlFor={`token-day-${day.key}`}
                          className="flex cursor-pointer items-center gap-2 text-sm text-neutral-950 dark:text-white"
                        >
                          <Checkbox
                            id={`token-day-${day.key}`}
                            checked={allowedDays.includes(day.value)}
                            onCheckedChange={(value) => toggleDay(day.value, value === true)}
                          />
                          {intl.formatMessage({ id: `tokens.form.day.${day.key}` })}
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {errors.submit && (
              <div
                className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                role="alert"
                aria-live="assertive"
              >
                {errors.submit}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="ghost" onClick={onCancel} disabled={isSubmitting}>
                {intl.formatMessage({ id: "tokens.form.cancel" })}
              </Button>
              <Button type="submit" disabled={isSubmitting || !name.trim()}>
                {isSubmitting
                  ? intl.formatMessage({ id: "tokens.form.submitting" })
                  : intl.formatMessage({ id: "tokens.form.submit" })}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
