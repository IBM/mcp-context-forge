import { MCPIcon } from "@/components/icons/MCPIcon";
import { NewMCPServerModal } from "@/components/mcpServers/NewMCPServerModal";
import { useRouter } from "@/router";

export function Servers() {
  const { navigate } = useRouter();

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-orange-500 text-white shadow-sm">
              <MCPIcon className="h-5 w-5 [&_path]:fill-white" />
            </div>
            <h2 className="text-xl font-semibold text-neutral-950">Connect MCP server</h2>
          </div>

          <p className="text-sm leading-relaxed text-neutral-600">
            Register a MCP server to federate its tools, resources, and prompts. Or,{" "}
            <button
              type="button"
              onClick={() => navigate("/app/server-catalog")}
              className="font-medium text-cyan-700 underline decoration-cyan-300 underline-offset-4 transition hover:text-cyan-800"
            >
              select from available servers
            </button>
            .
          </p>

          <NewMCPServerModal
            triggerLabel="Connect"
            triggerVariant="default"
            showTriggerIcon={true}
          />
        </div>
      </div>
    </div>
  );
}
