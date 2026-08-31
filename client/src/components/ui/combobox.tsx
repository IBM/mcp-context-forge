import * as React from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

export interface ComboboxOption {
  value: string;
  label: string;
  searchText?: string; // extra text to match against (e.g. raw email + full_name)
}

interface ComboboxProps {
  options: ComboboxOption[];
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
  allowCustomValue?: boolean;
}

// Navigable dropdown entries: either an existing option or a "use custom value" action.
type ComboboxItem = { kind: "option"; option: ComboboxOption } | { kind: "custom"; value: string };

export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = "Select option...",
  searchPlaceholder = "Search...",
  emptyText = "No option found.",
  className,
  disabled = false,
  allowCustomValue = true,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(-1);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listboxId = React.useId();
  const optionIdPrefix = React.useId();

  const selectedOption = options.find((opt) => opt.value === value);
  const displayLabel = selectedOption?.label || value || "";

  const filteredOptions = React.useMemo(() => {
    if (!searchValue) return options;
    const lower = searchValue.toLowerCase();
    return options.filter(
      (opt) =>
        opt.label.toLowerCase().includes(lower) ||
        opt.value.toLowerCase().includes(lower) ||
        (opt.searchText && opt.searchText.toLowerCase().includes(lower)),
    );
  }, [options, searchValue]);

  // Flattened, navigable list of dropdown entries (options + optional custom action).
  const items = React.useMemo<ComboboxItem[]>(() => {
    const trimmed = searchValue.trim();
    const result: ComboboxItem[] = filteredOptions.map((option) => ({ kind: "option", option }));
    const hasExactMatch = filteredOptions.some(
      (opt) => opt.value.toLowerCase() === trimmed.toLowerCase(),
    );
    if (allowCustomValue && trimmed && !hasExactMatch) {
      result.push({ kind: "custom", value: trimmed });
    }
    return result;
  }, [filteredOptions, searchValue, allowCustomValue]);

  const optionId = (index: number) => `${optionIdPrefix}-${index}`;

  // Keep the highlighted entry valid as the filtered list changes.
  React.useEffect(() => {
    setActiveIndex(items.length > 0 ? 0 : -1);
  }, [items]);

  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open || activeIndex < 0) return;
    listRef.current?.querySelector(`#${CSS.escape(optionId(activeIndex))}`)?.scrollIntoView({
      block: "nearest",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, open]);

  const handleOpen = () => {
    if (!disabled) {
      setOpen(true);
      setSearchValue("");
    }
  };

  const commitItem = (item: ComboboxItem) => {
    onValueChange?.(item.kind === "option" ? item.option.value : item.value);
    setOpen(false);
    setSearchValue("");
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchValue(e.target.value);
    if (!open) setOpen(true);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case "ArrowDown":
        if (!open) {
          setOpen(true);
          return;
        }
        if (items.length > 0) {
          e.preventDefault();
          setActiveIndex((prev) => (prev + 1) % items.length);
        }
        break;
      case "ArrowUp":
        if (open && items.length > 0) {
          e.preventDefault();
          setActiveIndex((prev) => (prev - 1 + items.length) % items.length);
        }
        break;
      case "Home":
        if (open && items.length > 0) {
          e.preventDefault();
          setActiveIndex(0);
        }
        break;
      case "End":
        if (open && items.length > 0) {
          e.preventDefault();
          setActiveIndex(items.length - 1);
        }
        break;
      case "Enter":
        if (open && activeIndex >= 0 && activeIndex < items.length) {
          e.preventDefault();
          commitItem(items[activeIndex]);
        }
        break;
      case "Escape":
        if (open) {
          e.preventDefault();
          setOpen(false);
          setSearchValue("");
        }
        break;
    }
  };

  const handleBlur = () => {
    setTimeout(() => {
      if (!containerRef.current?.contains(document.activeElement)) {
        setOpen(false);
        setSearchValue("");
      }
    }, 150);
  };

  const activeDescendant = open && activeIndex >= 0 ? optionId(activeIndex) : undefined;

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div className="relative flex h-full items-center">
        <Input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listboxId : undefined}
          aria-activedescendant={activeDescendant}
          aria-autocomplete="list"
          value={open ? searchValue : displayLabel}
          placeholder={open ? searchPlaceholder : placeholder}
          onChange={handleInputChange}
          onFocus={handleOpen}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          disabled={disabled}
          autoComplete="off"
          className={cn("h-full pr-8", !value && !open && "text-muted-foreground")}
        />
        <ChevronsUpDown
          className="pointer-events-none absolute right-2.5 h-4 w-4 shrink-0 opacity-50"
          aria-hidden="true"
        />
      </div>

      {open && (
        <div
          ref={listRef}
          id={listboxId}
          role="listbox"
          className="absolute top-full z-50 mt-1 max-h-[300px] w-full overflow-y-auto rounded-md border border-border bg-popover text-popover-foreground shadow-md"
        >
          {items.length === 0 ? (
            <div className="py-6 text-center text-sm text-muted-foreground">{emptyText}</div>
          ) : (
            <div className="p-1">
              {items.map((item, index) => {
                const isActive = index === activeIndex;
                const isSelected = item.kind === "option" && value === item.option.value;
                return (
                  <div
                    key={item.kind === "option" ? item.option.value : `__custom__${item.value}`}
                    id={optionId(index)}
                    role="option"
                    aria-selected={isSelected}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => commitItem(item)}
                    className={cn(
                      "flex h-auto w-full cursor-pointer items-center rounded-sm px-2 py-1.5 text-sm font-normal",
                      isActive && "bg-accent text-accent-foreground",
                      item.kind === "custom" &&
                        index > 0 &&
                        "mt-1 border-t border-border rounded-none rounded-b-sm",
                    )}
                  >
                    {item.kind === "option" ? (
                      <>
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4 shrink-0",
                            isSelected ? "opacity-100" : "opacity-0",
                          )}
                          aria-hidden="true"
                        />
                        {item.option.label}
                      </>
                    ) : (
                      <>Use &quot;{item.value}&quot;</>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
