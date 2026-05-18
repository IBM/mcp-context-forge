import { BookOpen } from "lucide-react";
import { useQuery } from "../../hooks/useQuery";
import { GitHubIcon } from "../icons/GitHubIcon";
import { SidebarTrigger } from "../ui/sidebar";
import { HeaderProfileMenu } from "./HeaderProfileMenu";
import { HeaderQuickNav } from "./HeaderQuickNav";

interface VersionResponse {
  app?: {
    version?: string;
  };
}

export function Header() {
  const { data: versionData } = useQuery<VersionResponse>("/version?partial=false");
  const appVersion = versionData?.app?.version;

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      <SidebarTrigger />
      <div className="flex items-center gap-2">
        <HeaderQuickNav />
        {appVersion ? (
          <span className="hidden text-sm font-medium text-muted-foreground sm:inline">
            v{appVersion}
          </span>
        ) : null}
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
