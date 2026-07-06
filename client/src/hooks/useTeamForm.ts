import { useState, useCallback, useEffect, useMemo, type FormEvent } from "react";
import { useIntl } from "react-intl";
import { toast } from "sonner";
import { z } from "zod";
import { api } from "@/api/client";
import { createTeam, addTeamMember } from "@/api/teams";
import { sanitizeError } from "@/utils/errors";
import type { ComboboxOption } from "@/components/ui/combobox";
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
  name: string;
  description: string;
  visibility: TeamVisibility;
  maxMembers: string;
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

export function useTeamForm(): UseTeamFormReturn {
  const intl = useIntl();
  const schema = useMemo(() => createTeamFormSchema(intl), [intl]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<TeamVisibility>("private");
  const [maxMembers, setMaxMembers] = useState(DEFAULT_MAX_MEMBERS);
  const [members, setMembers] = useState<TeamMember[]>(INITIAL_MEMBERS);
  const [memberOptions, setMemberOptions] = useState<ComboboxOption[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setName("");
    setDescription("");
    setVisibility("private");
    setMaxMembers(DEFAULT_MAX_MEMBERS);
    setMembers([{ email: "", role: "owner" }]);
    setError(null);
  }, []);

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
        const team = await createTeam({
          name: name.trim(),
          description: description.trim() || undefined,
          visibility,
          max_members: parseInt(maxMembers, 10),
        });

        const filledMembers = members.filter((m) => m.email.trim());
        if (filledMembers.length > 0) {
          const results = await Promise.allSettled(
            filledMembers.map((m) =>
              addTeamMember(team.id, { email: m.email.trim(), role: m.role }),
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
              intl.formatMessage({ id: "teams.create.warning.membersFailed" }, { name: team.name }),
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
    [name, description, visibility, maxMembers, members, intl, validateForm, resetForm],
  );

  return {
    name,
    description,
    visibility,
    maxMembers,
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
