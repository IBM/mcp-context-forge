import { BookOpen } from "lucide-react";
import { useQuery } from "../../hooks/useQuery";
import { GitHubIcon } from "../icons/GitHubIcon";
import { SidebarTrigger } from "../ui/sidebar";
import { HeaderProfileMenu } from "./HeaderProfileMenu";
import { HeaderQuickNav } from "./HeaderQuickNav";

const GITHUB_URL = "https://github.com/IBM/mcp-context-forge";
const DOCS_URL = "https://ibm.github.io/mcp-context-forge/latest/";

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
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="GitHub"
        >
          <GitHubIcon className="size-4" aria-hidden="true" />
        </a>
        <a
          href={DOCS_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Documentation"
        >
          <BookOpen className="size-4" aria-hidden="true" />
        </a>
        <HeaderProfileMenu />
      </div>
    </header>
  );
}
