import { useState, useCallback, useEffect, useMemo, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { z } from "zod";
import { api } from "@/api/client";
import { createTeam, updateTeam, addTeamMember } from "@/api/teams";
import { sanitizeError } from "@/utils/errors";
import type { ComboboxOption } from "@/components/ui/combobox";
import type { Team } from "@/types/team";
import type { UsersResponse } from "@/types/user";

export type TeamRole = "member" | "owner";
export type TeamVisibility = "private" | "public";

export interface TeamMember {
  email: string;
  role: TeamRole;
}

const createTeamFormSchema = (intl: ReturnType<typeof useIntl>) =>
  z.object({
    name: z
      .string()
      .trim()
      .min(1, intl.formatMessage({ id: "teams.create.error.nameRequired" }))
      .regex(/^[a-zA-Z0-9_.\- ]+$/, intl.formatMessage({ id: "teams.create.nameHint" })),
    // Only filled member rows are validated; empty rows are dropped before parsing.
    members: z.array(
      z.object({
        email: z
          .string()
          .trim()
          .email(intl.formatMessage({ id: "teams.create.error.invalidEmail" })),
        role: z.enum(["member", "owner"]),
      }),
    ),
  });

export interface UseTeamFormReturn {
  // State
  isEditMode: boolean;
  name: string;
  description: string;
  visibility: TeamVisibility;
  maxMembers: string;
  maxMembersOptions: string[];
  members: TeamMember[];
  memberOptions: ComboboxOption[];
  error: string | null;
  isSubmitting: boolean;

  // Setters
  setName: (value: string) => void;
  setDescription: (value: string) => void;
  setVisibility: (value: TeamVisibility) => void;
  setMaxMembers: (value: string) => void;

  // Member row actions
  handleAddMember: () => void;
  handleRemoveMember: (index: number) => void;
  handleMemberEmailChange: (index: number, value: string) => void;
  handleMemberRoleChange: (index: number, value: TeamRole) => void;

  // Form actions
  resetForm: () => void;
  validateForm: () => boolean;
  handleSubmit: (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => Promise<void>;
}

const INITIAL_MEMBERS: TeamMember[] = [{ email: "", role: "owner" }];
const DEFAULT_MAX_MEMBERS = "100";
const MAX_MEMBERS_PRESETS = ["10", "25", "50", "100", "250", "500"];

/**
 * The stringified max-members value the form shows for a team. Falls back to the
 * default when the team has no per-team override (`max_members` is null), which
 * mirrors the global default the backend would apply.
 */
const initialMaxMembers = (team?: Team): string =>
  team?.max_members != null ? String(team.max_members) : DEFAULT_MAX_MEMBERS;

/**
 * Manages the create/edit team form state.
 *
 * Pass an existing `team` to run in edit mode: the form is pre-populated with
 * the team's details and submitting issues a PUT instead of a POST. Member
 * management is only offered when creating a team — the update endpoint does
 * not touch membership, which is managed through its own dedicated flow.
 */
export function useTeamForm(team?: Team): UseTeamFormReturn {
  const intl = useIntl();
  const schema = useMemo(() => createTeamFormSchema(intl), [intl]);

  const isEditMode = team != null;

  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [visibility, setVisibility] = useState<TeamVisibility>(team?.visibility ?? "private");
  const [maxMembers, setMaxMembers] = useState(() => initialMaxMembers(team));
  const [members, setMembers] = useState<TeamMember[]>(INITIAL_MEMBERS);
  const [memberOptions, setMemberOptions] = useState<ComboboxOption[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A team's max_members may fall outside the preset list (e.g. an admin set a
  // custom cap via the API). Surface the current value as a selectable option so
  // the dropdown reflects it instead of rendering blank.
  const maxMembersOptions = useMemo(
    () =>
      MAX_MEMBERS_PRESETS.includes(maxMembers)
        ? MAX_MEMBERS_PRESETS
        : [...MAX_MEMBERS_PRESETS, maxMembers].sort((a, b) => Number(a) - Number(b)),
    [maxMembers],
  );

  // Load the directory of users for member autocomplete suggestions.
  useEffect(() => {
    let cancelled = false;
    api
      .get<UsersResponse>("/auth/email/admin/users?limit=0&include_pagination=true")
      .then((response) => {
        if (cancelled) return;
        const options = response.users.map((user) => ({
          value: user.email,
          label: user.full_name ? `${user.full_name} (${user.email})` : user.email,
          searchText: [user.full_name, user.email].filter(Boolean).join(" "),
        }));
        setMemberOptions(options);
      })
      .catch((err) => {
        console.error("Failed to fetch users for member suggestions:", sanitizeError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resetForm = useCallback(() => {
    setName(team?.name ?? "");
    setDescription(team?.description ?? "");
    setVisibility(team?.visibility ?? "private");
    setMaxMembers(initialMaxMembers(team));
    setMembers([{ email: "", role: "owner" }]);
    setError(null);
  }, [team]);

  const handleAddMember = useCallback(() => {
    setMembers((prev) => [...prev, { email: "", role: "owner" }]);
  }, []);

  const handleRemoveMember = useCallback((index: number) => {
    setMembers((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleMemberEmailChange = useCallback((index: number, value: string) => {
    setMembers((prev) => prev.map((m, i) => (i === index ? { ...m, email: value } : m)));
  }, []);

  const handleMemberRoleChange = useCallback((index: number, value: TeamRole) => {
    setMembers((prev) => prev.map((m, i) => (i === index ? { ...m, role: value } : m)));
  }, []);

  const validateForm = useCallback((): boolean => {
    const filledMembers = members.filter((m) => m.email.trim());
    const result = schema.safeParse({ name, members: filledMembers });
    if (result.success) {
      setError(null);
      return true;
    }
    setError(result.error.issues[0]?.message ?? null);
    return false;
  }, [name, members, schema]);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>, onSuccess?: () => void) => {
      event.preventDefault();
      setError(null);

      if (!validateForm()) return;

      setIsSubmitting(true);
      try {
        if (isEditMode) {
          // Only send max_members when the user actually changed it. Omitting it
          // preserves the team's existing value — including a null "no override"
          // that the backend would otherwise leave untouched, rather than
          // silently pinning it to the displayed default.
          const maxMembersChanged = maxMembers !== initialMaxMembers(team);
          await updateTeam(team.id, {
            name: name.trim(),
            // Send the trimmed value (an empty string when cleared) rather than
            // `undefined`. The backend only overwrites the description when the
            // field is present and non-null, so omitting it would silently keep
            // the old value when a user intends to clear it.
            description: description.trim(),
            visibility,
            ...(maxMembersChanged ? { max_members: parseInt(maxMembers, 10) } : {}),
          });
          onSuccess?.();
          return;
        }

        const createdTeam = await createTeam({
          name: name.trim(),
          description: description.trim() || undefined,
          visibility,
          max_members: parseInt(maxMembers, 10),
        });

        const filledMembers = members.filter((m) => m.email.trim());
        if (filledMembers.length > 0) {
          const results = await Promise.allSettled(
            filledMembers.map((m) =>
              addTeamMember(createdTeam.id, { email: m.email.trim(), role: m.role }),
            ),
          );
          const failed = results
            .map((r, i) =>
              r.status === "rejected"
                ? `${filledMembers[i].email}: ${sanitizeError(r.reason)}`
                : null,
            )
            .filter((v): v is string => v !== null);
          // The team was already created, so close the form and surface the
          // partial failure via a toast rather than blocking on an inline error
          // (which would tempt the user to resubmit and create a duplicate team).
          if (failed.length > 0) {
            toast.warning(
              intl.formatMessage(
                { id: "teams.create.warning.membersFailed" },
                { name: createdTeam.name },
              ),
              { description: failed.join("\n") },
            );
          }
        }

        resetForm();
        onSuccess?.();
      } catch (err) {
        setError(sanitizeError(err));
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      isEditMode,
      team,
      name,
      description,
      visibility,
      maxMembers,
      members,
      intl,
      validateForm,
      resetForm,
    ],
  );

  return {
    isEditMode,
    name,
    description,
    visibility,
    maxMembers,
    maxMembersOptions,
    members,
    memberOptions,
    error,
    isSubmitting,
    setName,
    setDescription,
    setVisibility,
    setMaxMembers,
    handleAddMember,
    handleRemoveMember,
    handleMemberEmailChange,
    handleMemberRoleChange,
    resetForm,
    validateForm,
    handleSubmit,
  };
}
