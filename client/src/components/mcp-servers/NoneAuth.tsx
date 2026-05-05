import { Zap } from "lucide-react";

export function NoneAuth() {
  return (
    <div className="flex gap-3 items-center rounded-md bg-neutral-50 px-3 py-5 dark:bg-neutral-800">
      <Zap className="h-5 w-5 shrink-0 text-neutral-500 dark:text-neutral-400" />
      <div className="space-y-1 text-sm text-neutral-600 dark:text-neutral-400">
        <p>
          No credentials are required to connect. Add authentication before using this server in
          production. Learn about best practices from the{" "}
          <a
            href="https://ibm.github.io/mcp-context-forge/1.0.0-RC3/manage/securing/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-700 underline hover:text-cyan-800 dark:text-cyan-400 dark:hover:text-cyan-300"
          >
            Production Security Checklist
          </a>
          .
        </p>
      </div>
    </div>
  );
}
