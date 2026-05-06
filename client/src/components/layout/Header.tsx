import { BookOpen } from "lucide-react";
import appPackage from "../../../package.json";
import { GitHubIcon } from "../icons/GitHubIcon";
import { MainNavIcon } from "../icons/MainNavIcon";
import { SidebarTrigger } from "../ui/sidebar";
import { HeaderProfileMenu } from "./HeaderProfileMenu";
import { HeaderQuickNav } from "./HeaderQuickNav";
import { TeamSwitcher } from "./TeamSwitcher";

export function Header() {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center shrink-0">
          <MainNavIcon className="h-6 w-6" />
        </div>
        <SidebarTrigger />
        <TeamSwitcher />
      </div>
      <div className="flex items-center gap-2">
        <HeaderQuickNav />
        <span className="hidden text-sm font-medium text-muted-foreground sm:inline">
          v{appPackage.version}
        </span>
        <a
          href="https://github.com/IBM/mcp-context-forge"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="GitHub"
          title="GitHub"
        >
          <GitHubIcon className="size-4" aria-hidden="true" />
        </a>
        <a
          href="https://ibm.github.io/mcp-context-forge/latest/"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Documentation"
          title="Documentation"
        >
          <BookOpen className="size-4" aria-hidden="true" />
        </a>
        <HeaderProfileMenu />
      </div>
    </header>
  );
}
