import { ChevronDown, LogOut, Monitor, Moon, Settings2, Sun } from "lucide-react";
import { useIntl } from "react-intl";
import { useAuth } from "../../auth/useAuth";
import { useTheme } from "../../hooks/useTheme";
import { useRouter } from "../../router";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

export function HeaderProfileMenu() {
  const intl = useIntl();
  const { user, logout } = useAuth();
  const { navigate } = useRouter();
  const { theme, setTheme } = useTheme();

  if (!user) return null;

  const displayName = user.full_name || user.email;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {/* TODO: User photo/avatar data does not appear to be available in the current frontend. Using fallback button for now. */}
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 rounded-lg px-1.5 hover:bg-muted"
          aria-label={displayName}
        >
          <span className="block size-6 overflow-hidden rounded-md bg-muted" aria-hidden="true" />
          <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72 rounded-xl p-2">
        <DropdownMenuLabel className="px-3 py-2 text-sm font-normal text-muted-foreground">
          {user.email}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="flex items-center justify-between gap-3 px-3 py-2">
          <span className="text-sm">{intl.formatMessage({ id: "common.theme" })}</span>
          <div className="flex items-center gap-1 rounded-full bg-muted p-1">
            <button
              type="button"
              onClick={() => setTheme("light")}
              className={`rounded-full p-1.5 transition-colors ${theme === "light" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              aria-label={intl.formatMessage({ id: "common.theme.light" })}
              title={intl.formatMessage({ id: "common.theme.light" })}
            >
              <Sun className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => setTheme("dark")}
              className={`rounded-full p-1.5 transition-colors ${theme === "dark" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              aria-label={intl.formatMessage({ id: "common.theme.dark" })}
              title={intl.formatMessage({ id: "common.theme.dark" })}
            >
              <Moon className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => setTheme("system")}
              className={`rounded-full p-1.5 transition-colors ${theme === "system" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              aria-label={intl.formatMessage({ id: "common.theme.system" })}
              title={intl.formatMessage({ id: "common.theme.system" })}
            >
              <Monitor className="size-4" />
            </button>
          </div>
        </div>
        <DropdownMenuItem
          onClick={() => navigate("/app/settings")}
          className="gap-2 rounded-lg px-3 py-2"
        >
          <Settings2 className="size-4" aria-hidden="true" />
          {intl.formatMessage({ id: "navigation.settings" })}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={logout} className="gap-2 rounded-lg px-3 py-2">
          <LogOut className="size-4" aria-hidden="true" />
          {intl.formatMessage({ id: "auth.logout" })}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
