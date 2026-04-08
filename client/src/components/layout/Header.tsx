import { useAuth } from "../../auth/useAuth";
import { SidebarTrigger } from "../ui/sidebar";

export function Header() {
  const { user, logout } = useAuth();

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      <SidebarTrigger />
      <div className="flex items-center gap-3">
        {user && (
          <span className="text-sm text-muted-foreground">{user.email}</span>
        )}
        <button
          onClick={logout}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
