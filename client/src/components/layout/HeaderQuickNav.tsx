import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useIntl } from "react-intl";
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
        className="relative"
      >
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={intl.formatMessage({ id: "common.search" })}
          className="h-8 w-44 rounded-lg border-border bg-muted/50 pl-8 pr-12 text-sm shadow-none md:w-48 lg:w-56"
        />
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground">
          {shortcutLabel}
        </span>
      </form>
      {/* Quick-navigation behavior will be added here once the search flow is defined for the UI rewrite. */}
    </div>
  );
}
