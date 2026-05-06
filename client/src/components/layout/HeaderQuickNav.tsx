import { useState } from "react";
import { Search } from "lucide-react";
import { useIntl } from "react-intl";
import { Input } from "../ui/input";

export function HeaderQuickNav() {
  const intl = useIntl();
  const [query, setQuery] = useState("");

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
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={intl.formatMessage({ id: "common.search" })}
          aria-label={intl.formatMessage({ id: "common.search" })}
          className="h-8 w-44 rounded-lg border-border bg-muted/50 pl-8 pr-12 text-sm shadow-none md:w-48 lg:w-56"
        />
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          K
        </span>
      </form>
      {/* Quick-navigation behavior will be added here once the search flow is defined for the UI rewrite. */}
    </div>
  );
}
