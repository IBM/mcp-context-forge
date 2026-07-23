import { useId, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { CardTag } from "@/components/ui/card-tag";

const SPLIT_PATTERN = /[,\n\t]/;

export interface TagInputProps {
  id?: string;
  value: string[];
  onChange: (next: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
  maxTags?: number;
  disabled?: boolean;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
  "aria-labelledby"?: string;
  className?: string;
}

type Suggestion = { kind: "existing"; value: string } | { kind: "create"; value: string };

export function TagInput({
  id,
  value,
  onChange,
  suggestions = [],
  placeholder,
  maxTags,
  disabled = false,
  className,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
  "aria-labelledby": ariaLabelledBy,
}: TagInputProps) {
  const [text, setText] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const optionPrefix = useId();

  const atMax = maxTags !== undefined && value.length >= maxTags;

  const addTags = (raw: string[]) => {
    const seen = new Set(value.map((tag) => tag.toLowerCase()));
    const next = [...value];
    for (const candidate of raw) {
      const tag = candidate.trim();
      if (!tag) continue;
      if (maxTags !== undefined && next.length >= maxTags) break;
      const key = tag.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      next.push(tag);
    }
    if (next.length !== value.length) onChange(next);
    setText("");
    setActiveIndex(-1);
  };

  const removeAt = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
    inputRef.current?.focus();
  };

  const options = useMemo<Suggestion[]>(() => {
    const query = text.trim().toLowerCase();
    const selected = new Set(value.map((tag) => tag.toLowerCase()));
    const matches: Suggestion[] = suggestions
      .filter((tag) => !selected.has(tag.toLowerCase()))
      .filter((tag) => query === "" || tag.toLowerCase().includes(query))
      .map((tag) => ({ kind: "existing", value: tag }));

    const query0 = text.trim();
    const isNew =
      query0 !== "" &&
      !selected.has(query0.toLowerCase()) &&
      !matches.some((m) => m.value.toLowerCase() === query0.toLowerCase());
    return isNew ? [...matches, { kind: "create", value: query0 }] : matches;
  }, [suggestions, text, value]);

  const open = focused && options.length > 0;

  const commitActiveOrText = () => {
    if (activeIndex >= 0 && activeIndex < options.length) {
      addTags([options[activeIndex].value]);
    } else if (text.trim()) {
      addTags([text]);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitActiveOrText();
      return;
    }
    if (event.key === "Tab") {
      if (text.trim() || activeIndex >= 0) {
        event.preventDefault();
        commitActiveOrText();
      }
      return;
    }
    if (event.key === "Backspace" && text === "" && value.length > 0) {
      event.preventDefault();
      removeAt(value.length - 1);
      return;
    }
    if (event.key === "ArrowDown" && options.length > 0) {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % options.length);
      return;
    }
    if (event.key === "ArrowUp" && options.length > 0) {
      event.preventDefault();
      setActiveIndex((i) => (i <= 0 ? options.length - 1 : i - 1));
      return;
    }
    if (event.key === "Escape") {
      setActiveIndex(-1);
      setText("");
    }
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text");
    if (SPLIT_PATTERN.test(pasted)) {
      event.preventDefault();
      addTags(pasted.split(SPLIT_PATTERN));
    }
  };

  const handleBlur = () => {
    if (text.trim()) addTags([text]);
    setActiveIndex(-1);
    setFocused(false);
  };

  return (
    <div
      role="group"
      aria-labelledby={ariaLabelledBy}
      className={cn(
        "flex flex-wrap items-center gap-1.5 rounded-md border border-neutral-300 bg-transparent px-2 py-1.5 focus-within:ring-1 focus-within:ring-ring dark:border-neutral-700",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {value.map((tag, index) => (
        <CardTag key={`${tag}-${index}`} variant="neutral" className="gap-1">
          {tag}
          <button
            type="button"
            aria-label={`Remove ${tag}`}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation();
              removeAt(index);
            }}
            className="rounded-sm text-neutral-500 hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring dark:hover:text-white"
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </CardTag>
      ))}
      <div className="relative min-w-[8rem] flex-1">
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && activeIndex >= 0 ? `${optionPrefix}-${activeIndex}` : undefined
          }
          aria-invalid={ariaInvalid}
          aria-describedby={ariaDescribedBy}
          value={text}
          disabled={disabled || atMax}
          placeholder={atMax ? undefined : placeholder}
          onChange={(event) => {
            setText(event.target.value);
            setActiveIndex(-1);
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onBlur={handleBlur}
          onFocus={() => setFocused(true)}
          className="w-full bg-transparent text-sm text-neutral-900 outline-none placeholder:text-neutral-400 disabled:cursor-not-allowed dark:text-neutral-100 dark:placeholder:text-neutral-500"
        />
        {open && (
          <ul
            id={listboxId}
            role="listbox"
            className="absolute left-0 top-full z-50 mt-1 max-h-56 w-full min-w-[12rem] overflow-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
          >
            {options.map((option, index) => (
              <li
                key={`${option.kind}-${option.value}`}
                id={`${optionPrefix}-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                onMouseDown={(event) => {
                  event.preventDefault();
                  addTags([option.value]);
                }}
                onMouseEnter={() => setActiveIndex(index)}
                className={cn(
                  "cursor-pointer rounded-sm px-2 py-1.5 text-sm",
                  index === activeIndex && "bg-accent text-accent-foreground",
                )}
              >
                {option.kind === "create" ? `Create "${option.value}"` : option.value}
              </li>
            ))}
          </ul>
        )}
      </div>
      {atMax && (
        <p role="status" className="basis-full text-xs text-muted-foreground">
          Maximum {maxTags} tags reached.
        </p>
      )}
    </div>
  );
}
