import { useIntl } from "react-intl";
import { useAuth } from "../../auth/useAuth";
import { LanguageSwitcher } from "../ui/LanguageSwitcher";
import { ThemeToggle } from "../ui/ThemeToggle";
import { SidebarTrigger } from "../ui/sidebar";

export function Header() {
  const intl = useIntl();
  const { user, logout } = useAuth();

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      <SidebarTrigger />
      <div className="flex items-center gap-3">
        <LanguageSwitcher />
        <ThemeToggle />
        {user && <span className="text-sm text-muted-foreground">{user.email}</span>}
        <button
          onClick={logout}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          {intl.formatMessage({ id: "auth.logout" })}
        </button>
      </div>
    </header>
  );
}
