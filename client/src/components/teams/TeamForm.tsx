import { Fragment } from "react";
import { useIntl } from "react-intl";
import { ArrowLeft, Lock, Plus, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { Combobox } from "@/components/ui/combobox";
import { useTeamForm } from "@/hooks/useTeamForm";

interface CreateTeamFormProps {
  isOpen: boolean;
  onToggle: () => void;
  onSuccess: () => void;
}

export function TeamForm({ isOpen, onToggle, onSuccess }: CreateTeamFormProps) {
  const intl = useIntl();
  const {
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
    handleMemberNameChange,
    handleMemberRoleChange,
    resetForm,
    handleSubmit,
  } = useTeamForm();

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) =>
    handleSubmit(e, () => {
      onSuccess();
      onToggle();
    });

  const handleCancel = () => {
    resetForm();
    onToggle();
  };

  if (!isOpen) return null;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <Button
        variant="ghost"
        size="sm"
        className="mb-4 gap-1.5 px-2 text-sm text-neutral-400 hover:text-neutral-700 dark:text-neutral-300 dark:hover:text-white"
        onClick={handleCancel}
        type="button"
      >
        <ArrowLeft className="h-4 w-4" />
        {intl.formatMessage({ id: "common.button.back" })}
      </Button>

      <div className="rounded-xl border border-neutral-200 bg-inherit shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex flex-col gap-8 p-6 sm:p-8">
          {/* Header */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-yellow-400 shadow-sm">
                <Users className="h-4 w-4 text-neutral-900" />
              </div>
              <h2
                id="create-team-form-title"
                className="align-middle text-base font-semibold leading-6 tracking-normal text-neutral-950 dark:text-neutral-50"
              >
                {intl.formatMessage({ id: "teams.create.title" })}
              </h2>
            </div>
            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              {intl.formatMessage({ id: "teams.create.description" })}
            </p>
          </div>

          <form onSubmit={onSubmit} className="space-y-5" aria-labelledby="create-team-form-title">
            {/* Name */}
            <div className="space-y-2">
              <Label
                htmlFor="team-name"
                className="text-sm font-medium text-neutral-950 dark:text-white"
              >
                {intl.formatMessage({ id: "teams.create.name" })}{" "}
                <span className="text-red-500" aria-hidden="true">
                  *
                </span>
              </Label>
              <Input
                id="team-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={intl.formatMessage({ id: "teams.create.namePlaceholder" })}
                disabled={isSubmitting}
                className="h-10 border-neutral-300 dark:border-neutral-700"
              />
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                {intl.formatMessage({ id: "teams.create.nameHint" })}
              </p>
            </div>

            {/* Description */}
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={intl.formatMessage({ id: "teams.create.descriptionPlaceholder" })}
              aria-label={intl.formatMessage({ id: "teams.create.descriptionLabel" })}
              disabled={isSubmitting}
              rows={3}
              className="resize-none border-neutral-300 dark:border-neutral-700"
            />

            {/* Visibility */}
            <div className="space-y-3">
              <Label className="text-sm font-medium text-neutral-950 dark:text-white">
                {intl.formatMessage({ id: "teams.create.visibility" })}
              </Label>
              <div
                role="radiogroup"
                aria-label={intl.formatMessage({ id: "teams.create.visibility" })}
                className="flex w-full gap-1 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
              >
                {(["private", "public"] as const).map((v) => (
                  <div key={v} className="min-w-0 flex-1">
                    <input
                      type="radio"
                      id={`visibility-${v}`}
                      name="visibility"
                      value={v}
                      checked={visibility === v}
                      onChange={() => setVisibility(v)}
                      className="peer sr-only"
                      disabled={isSubmitting}
                    />
                    <Label
                      htmlFor={`visibility-${v}`}
                      className="flex cursor-pointer items-center justify-center rounded-md px-3 py-2 text-center text-sm font-medium text-neutral-500 transition hover:bg-neutral-200 hover:text-neutral-700 peer-checked:bg-neutral-800 peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 dark:text-neutral-400 dark:hover:bg-neutral-900 dark:hover:text-neutral-300 dark:peer-checked:bg-neutral-950 dark:peer-checked:text-white"
                    >
                      {intl.formatMessage({ id: `teams.create.visibility.${v}` })}
                    </Label>
                  </div>
                ))}
              </div>
              {visibility === "private" && (
                <div className="flex items-center gap-3 rounded-md bg-neutral-50 px-3 py-5 dark:bg-neutral-800">
                  <Lock className="h-5 w-5 shrink-0 text-neutral-500 dark:text-neutral-400" />
                  <span className="text-sm text-neutral-600 dark:text-neutral-400">
                    {intl.formatMessage({ id: "teams.create.visibility.description" })}
                  </span>
                </div>
              )}
            </div>

            {/* Team Members */}
            <div className="space-y-3">
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                {intl.formatMessage({ id: "teams.create.membersHint" })}
              </p>

              {/* Single grid — labels + member rows share the same column tracks so
                  the auto Remove column is sized consistently across all rows */}
              <div className="grid grid-cols-[2fr_1fr_auto] items-center gap-x-2 gap-y-2">
                {/* Header labels */}
                <Label className="text-sm font-medium text-neutral-950 dark:text-white">
                  {intl.formatMessage({ id: "teams.create.memberName" })}
                </Label>
                <Label className="text-sm font-medium text-neutral-950 dark:text-white">
                  {intl.formatMessage({ id: "teams.create.roleLabel" })}
                </Label>
                <div />

                {/* One editable row per member */}
                {members.map((member, index) => (
                  <Fragment key={index}>
                    <Combobox
                      options={memberOptions}
                      value={member.name}
                      onValueChange={(v) => handleMemberNameChange(index, v)}
                      placeholder={intl.formatMessage({ id: "teams.create.memberPlaceholder" })}
                      searchPlaceholder={intl.formatMessage({
                        id: "teams.create.memberPlaceholder",
                      })}
                      emptyText={intl.formatMessage({ id: "teams.create.memberPlaceholder" })}
                      allowCustomValue={false}
                      disabled={isSubmitting}
                      className="h-10 border-neutral-300 dark:border-neutral-700"
                    />
                    <Select
                      value={member.role}
                      onValueChange={(v) => handleMemberRoleChange(index, v as "member" | "owner")}
                      disabled={isSubmitting}
                    >
                      <SelectTrigger className="h-10 w-full border-neutral-300 dark:border-neutral-700">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="member">
                          {intl.formatMessage({ id: "teams.create.role.member" })}
                        </SelectItem>
                        <SelectItem value="owner">
                          {intl.formatMessage({ id: "teams.create.role.owner" })}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveMember(index)}
                      disabled={isSubmitting}
                      className="h-10 gap-1.5 px-2 text-red-500 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {intl.formatMessage({ id: "common.button.remove" })}
                    </Button>
                  </Fragment>
                ))}
              </div>

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddMember}
                disabled={isSubmitting}
                className="gap-1.5 border-neutral-200 dark:border-neutral-600"
              >
                <Plus className="h-3.5 w-3.5" />
                {intl.formatMessage({ id: "teams.create.addMemberButton" })}
              </Button>
            </div>

            {/* Maximum Members */}
            <div className="space-y-2">
              <Label
                htmlFor="max-members"
                className="text-sm font-medium text-neutral-950 dark:text-white"
              >
                {intl.formatMessage({ id: "teams.create.maxMembers" })}
              </Label>
              <Select value={maxMembers} onValueChange={setMaxMembers} disabled={isSubmitting}>
                <SelectTrigger
                  id="max-members"
                  className="h-10 w-full border-neutral-300 dark:border-neutral-700"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="10">10</SelectItem>
                  <SelectItem value="25">25</SelectItem>
                  <SelectItem value="50">50</SelectItem>
                  <SelectItem value="100">100</SelectItem>
                  <SelectItem value="250">250</SelectItem>
                  <SelectItem value="500">500</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {error && (
              <div
                className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                role="alert"
              >
                {error}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="ghost" onClick={handleCancel} disabled={isSubmitting}>
                {intl.formatMessage({ id: "common.button.cancel" })}
              </Button>
              <Button type="submit" disabled={isSubmitting || !name.trim()}>
                {isSubmitting
                  ? intl.formatMessage({ id: "teams.create.creating" })
                  : intl.formatMessage({ id: "teams.create.submit" })}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
