import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useIntl } from "react-intl";
import { cn } from "@/lib/utils";
import { Input } from "../ui/input";

type ShortcutNavigator = Pick<Navigator, "platform" | "userAgent"> & {
  userAgentData?: {
    platform?: string;
  };
};

export function getQuickNavShortcutLabel(nav: ShortcutNavigator = navigator) {
  const detectedPlatform = [nav.userAgentData?.platform, nav.platform, nav.userAgent]
    .filter(Boolean)
    .join(" ");

  return /mac|iphone|ipad|ipod/i.test(detectedPlatform) ? "⌘ K" : "Ctrl K";
}

export function HeaderQuickNav() {
  const intl = useIntl();
  const [query, setQuery] = useState("");
  const [shortcutLabel, setShortcutLabel] = useState("Ctrl K");
  const [isExpanded, setIsExpanded] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setShortcutLabel(getQuickNavShortcutLabel());
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className="hidden md:block">
      <form
        onSubmit={(event) => event.preventDefault()}
        className="relative flex items-center gap-2"
      >
        <button
          type="button"
          onClick={() => inputRef.current?.focus()}
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={intl.formatMessage({ id: "common.search" })}
          title={intl.formatMessage({ id: "common.search" })}
        >
          <Search className="size-4" aria-hidden="true" />
        </button>
        <Input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setIsExpanded(true)}
          onBlur={() => setIsExpanded(query.length > 0)}
          aria-label={intl.formatMessage({ id: "common.search" })}
          data-expanded={isExpanded || query.length > 0}
          placeholder={isExpanded || query.length > 0 ? intl.formatMessage({ id: "common.search" }) : ""}
          className={cn(
            "h-8 rounded-lg border-border bg-muted/50 pr-2 text-sm shadow-none transition-[width,padding,color,background-color,border-color] duration-200 ease-out placeholder:text-muted-foreground/80 focus-visible:bg-background",
            isExpanded || query.length > 0
              ? "w-44 px-3 text-foreground md:w-48 lg:w-56"
              : "w-[3.9rem] px-2 text-transparent caret-foreground",
          )}
        />
        <span
          className={cn(
            "pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground transition-opacity duration-150",
            isExpanded || query.length > 0 ? "opacity-0" : "opacity-100",
          )}
        >
          {shortcutLabel}
        </span>
      </form>
      {/* Quick-navigation behavior will be added here once the search flow is defined for the UI rewrite. */}
    </div>
  );
}
