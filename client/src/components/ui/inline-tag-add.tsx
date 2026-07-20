import { useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface InlineTagAddProps {
  /** The detail-row label rendered in the left column (e.g. "Tags"). */
  label: string;
  /**
   * Existing tag chips, rendered in the value column beside the "+ add" trigger.
   * The caller owns chip markup so each drawer keeps its own styling.
   */
  children?: ReactNode;
  /**
   * Tag labels already applied to the entity. Used to skip duplicates
   * (case-insensitive) so the same tag is never sent twice.
   */
  existingTags: string[];
  /**
   * Persists one or more new tags (the input accepts a comma-separated list).
   * Receives the parsed, trimmed, de-duplicated new labels — appending them to
   * {@link existingTags} is the caller's job. Should resolve once the change is
   * saved and reject if it fails — on rejection the editor stays open with its
   * value so the user can retry (the caller surfaces the error, e.g. via toast).
   * When omitted the "+ add" trigger is rendered but disabled.
   */
  onAdd?: (tags: string[]) => Promise<void>;
  /** Text shown on the collapsed trigger button. Defaults to "add". */
  addLabel?: string;
  /** Placeholder for the inline input. Defaults to "Add tags separated with commas". */
  placeholder?: string;
  /** Accessible label for the trigger button and input. Defaults to "Add tag". */
  ariaLabel?: string;
  /** Label for the confirm button. Defaults to "Add". */
  submitLabel?: string;
  /** Label for the confirm button while the add is in flight. Defaults to "Adding...". */
  submitPendingLabel?: string;
  /** Label for the cancel button. Defaults to "Cancel". */
  cancelLabel?: string;
  /** Optional override for the trigger button classes. */
  triggerClassName?: string;
}

/**
 * "Tags" detail row with an inline add-tag interaction, used across the details
 * drawers.
 *
 * The label and existing chips sit on one row (a 2-column grid matching the
 * other detail rows). Clicking the compact "+ add" trigger replaces it with a
 * text input plus a Cancel / Add button row that spans the full width *below*
 * the label — matching the design. Cancel collapses back to the trigger; Add
 * persists the trimmed value via {@link InlineTagAddProps.onAdd} and, on
 * success, collapses back so the new tag shows among the chips. Duplicate labels
 * (matched case-insensitively against {@link InlineTagAddProps.existingTags})
 * are ignored rather than sent to the backend. Enter confirms and Escape
 * cancels as keyboard shortcuts.
 */
export function InlineTagAdd({
  label,
  children,
  existingTags,
  onAdd,
  addLabel = "add",
  placeholder = "Add tags separated with commas",
  ariaLabel = "Add tags",
  submitLabel = "Add",
  submitPendingLabel = "Adding...",
  cancelLabel = "Cancel",
  triggerClassName,
}: InlineTagAddProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = () => {
    setEditing(false);
    setValue("");
  };

  const submit = async () => {
    if (!onAdd) return;

    // Parse the comma-separated input into trimmed, unique new labels, skipping
    // blanks, existing tags, and repeats within the same input (all
    // case-insensitive).
    const seen = new Set(existingTags.map((t) => t.toLowerCase()));
    const newTags: string[] = [];
    for (const raw of value.split(",")) {
      const tag = raw.trim();
      if (!tag) continue;
      const key = tag.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      newTags.push(tag);
    }

    if (newTags.length === 0) {
      close();
      return;
    }

    setPending(true);
    try {
      await onAdd(newTags);
      close();
    } catch {
      // Leave the editor open with its value so the user can retry; the caller
      // surfaces the error (e.g. via toast).
    } finally {
      setPending(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void submit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };

  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-center gap-x-4 gap-y-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 flex-wrap items-center gap-2 text-foreground">
        {children}
        {!editing && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!onAdd}
            onClick={() => setEditing(true)}
            aria-label={ariaLabel}
            className={cn(
              "flex items-center gap-1 rounded text-[12px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
              triggerClassName,
            )}
          >
            <Plus className="size-3" aria-hidden="true" />
            {addLabel}
          </Button>
        )}
      </dd>

      {editing && (
        <div className="col-span-2 flex w-full min-w-0 flex-col gap-3">
          <Input
            ref={inputRef}
            autoFocus
            value={value}
            disabled={pending}
            aria-label={ariaLabel}
            placeholder={placeholder}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            className="h-8 w-full text-[12px] focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-0"
          />
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" size="xs" disabled={pending} onClick={close}>
              {cancelLabel}
            </Button>
            <Button
              type="button"
              size="xs"
              disabled={pending || value.trim().length === 0}
              onClick={() => void submit()}
            >
              {pending ? submitPendingLabel : submitLabel}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
