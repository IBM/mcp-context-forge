import { ChevronDown, CircleAlert, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { useRouter } from "@/router";

type TransportType = "sse" | "streamable-http";

interface NewMCPServerModalProps {
  triggerLabel?: string;
  triggerVariant?: "default" | "outline" | "secondary" | "ghost" | "destructive" | "link";
  showTriggerIcon?: boolean;
}

export function NewMCPServerModal({
  triggerLabel = "Connect",
  triggerVariant = "default",
  showTriggerIcon = true,
}: NewMCPServerModalProps) {
  const { navigate } = useRouter();
  const [open, setOpen] = useState(false);
  const [transport, setTransport] = useState<TransportType>("sse");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const resetForm = () => {
    setTransport("sse");
    setName("");
    setUrl("");
    setDescription("");
    setAdvancedOpen(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      resetForm();
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Handle form submission
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant={triggerVariant} className="h-10 w-fit rounded-lg px-4">
          {showTriggerIcon ? <Plus className="h-4 w-4" /> : null}
          {triggerLabel}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl rounded-[24px] border border-neutral-200 bg-white p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)]">
        <DialogHeader className="sr-only">
          <DialogTitle>Connect MCP server</DialogTitle>
          <DialogDescription>Create a new MCP server connection.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-8 p-6 sm:p-8">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-sm bg-orange-500 text-white shadow-sm">
                <MCPIcon className="h-5 w-5 [&_path]:fill-white" />
              </div>
              <h2 className="text-2xl font-semibold tracking-tight text-neutral-950">
                Connect MCP server
              </h2>
            </div>
            
            <p className="text-sm leading-6 text-neutral-600">
              Context Forge will discover the server's tools, resources, and prompts.
              The MCP server should be running and reachable. Or, choose a server from the{" "}
              <button
                type="button"
                onClick={() => {
                  handleOpenChange(false);
                  navigate("/app/server-catalog");
                }}
                className="font-medium text-cyan-700 underline decoration-cyan-300 underline-offset-4 transition hover:text-cyan-800"
              >
                mcp server catalog
              </button>
              .
            </p>
          </div>

          <form className="space-y-6" onSubmit={handleSubmit}>
            <div className="space-y-1">
              <label className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900">
                Server transport type
              </label>
              <div className="grid grid-cols-2 gap-2 rounded-md bg-neutral-100 p-1">
                <button
                  type="button"
                  onClick={() => setTransport("sse")}
                  className={`rounded-md px-4 py-2.5 text-sm font-medium transition ${
                    transport === "sse"
                      ? "bg-white text-neutral-950 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-800"
                  }`}
                  aria-pressed={transport === "sse"}
                >
                  SSE
                </button>
                <button
                  type="button"
                  onClick={() => setTransport("streamable-http")}
                  className={`rounded-md px-4 py-2.5 text-sm font-medium transition ${
                    transport === "streamable-http"
                      ? "bg-white text-neutral-950 shadow-sm"
                      : "text-neutral-500 hover:text-neutral-800"
                  }`}
                  aria-pressed={transport === "streamable-http"}
                >
                  Streamable HTTP
                </button>
              </div>
            </div>

            <div className="space-y-1">
              <label htmlFor="server-name" className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900">
                Name<span className="text-red-500">*</span>
              </label>
              <Input
                id="server-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Add MCP server name..."
                className="h-11 rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none placeholder:text-neutral-400"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="server-url"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900"
              >
                URL<span className="text-red-500">*</span>
                <CircleAlert className="h-4 w-4 text-neutral-400" />
              </label>
              <Input
                id="server-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="Add URL for a running MCP server..."
                className="h-11 rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none placeholder:text-neutral-400"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="server-description" className="sr-only">
                Description
              </label>
              <textarea
                id="server-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Add an optional description..."
                className="min-h-28 w-full rounded-md border border-neutral-300 bg-white px-4 py-3 text-sm text-neutral-900 shadow-none outline-none transition placeholder:text-neutral-400 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>

            <div className="flex flex-col gap-5 pt-2">
              <button
                type="button"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-fit items-center gap-2 text-sm font-medium text-neutral-700 transition hover:text-neutral-950"
                aria-expanded={advancedOpen}
              >
                <ChevronDown
                  className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`}
                />
                Advanced options
              </button>

              {advancedOpen ? (
                <div className="rounded-md border border-dashed border-neutral-300 bg-neutral-50 px-4 py-3 text-sm text-neutral-600">
                  Additional gateway configuration options can be added here.
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-3 border-t border-neutral-200 pt-6">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => handleOpenChange(false)}
                  className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:bg-neutral-800"
                >
                  Connect server
                </Button>
              </div>
            </div>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
