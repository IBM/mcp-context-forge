import { ChevronDown, CircleAlert, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
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
import { type VariantProps } from "class-variance-authority";

type TransportType = "sse" | "streamable-http";

interface NewMCPServerModalProps {
  triggerLabel?: string;
  triggerVariant?: VariantProps<typeof buttonVariants>["variant"];
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
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Handle form submission
    setOpen(false);
    resetForm();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant={triggerVariant} className="h-10 w-fit rounded-lg px-4">
          {showTriggerIcon && <Plus className="h-4 w-4" />}
          {triggerLabel}
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl rounded-[24px] border border-neutral-200 bg-white p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800 dark:bg-neutral-900">
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
              <h2 className="text-2xl font-semibold tracking-tight text-neutral-950 dark:text-neutral-50">
                Connect MCP server
              </h2>
            </div>

            <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
              Context Forge will discover the server&#39;s tools, resources, and prompts. The MCP
              server should be running and reachable. Or, choose a server from the{" "}
              <button
                type="button"
                onClick={() => {
                  handleOpenChange(false);
                  navigate("/app/server-catalog");
                }}
                className="font-medium text-cyan-700 underline decoration-cyan-300 underline-offset-4 transition hover:text-cyan-800 dark:text-cyan-400 dark:decoration-cyan-700 dark:hover:text-cyan-300"
              >
                mcp server catalog
              </button>
              .
            </p>
          </div>

          <form className="space-y-6" onSubmit={handleSubmit}>
            <div className="space-y-1">
              <div
                role="radiogroup"
                aria-label="Server transport type"
                className="grid grid-cols-2 gap-2 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800"
              >
                <input
                  type="radio"
                  id="transport-sse"
                  name="transport"
                  value="sse"
                  checked={transport === "sse"}
                  onChange={(e) => setTransport(e.target.value as TransportType)}
                  className="sr-only peer/sse"
                />
                <label
                  htmlFor="transport-sse"
                  className="cursor-pointer rounded-md px-4 py-2.5 text-sm font-medium transition peer-checked/sse:bg-white peer-checked/sse:text-neutral-950 peer-checked/sse:shadow-sm peer-focus-visible/sse:ring-2 peer-focus-visible/sse:ring-ring peer-focus-visible/sse:ring-offset-2 dark:peer-checked/sse:bg-neutral-900 dark:peer-checked/sse:text-neutral-50 text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
                >
                  SSE
                </label>

                <input
                  type="radio"
                  id="transport-http"
                  name="transport"
                  value="streamable-http"
                  checked={transport === "streamable-http"}
                  onChange={(e) => setTransport(e.target.value as TransportType)}
                  className="sr-only peer/http"
                />
                <label
                  htmlFor="transport-http"
                  className="cursor-pointer rounded-md px-4 py-2.5 text-sm font-medium transition peer-checked/http:bg-white peer-checked/http:text-neutral-950 peer-checked/http:shadow-sm peer-focus-visible/http:ring-2 peer-focus-visible/http:ring-ring peer-focus-visible/http:ring-offset-2 dark:peer-checked/http:bg-neutral-900 dark:peer-checked/http:text-neutral-50 text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
                >
                  Streamable HTTP
                </label>
              </div>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="server-name"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                Name<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <Input
                id="server-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Add MCP server name..."
                className="h-11 rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="server-url"
                className="inline-flex items-center gap-0.5 text-sm font-medium text-neutral-900 dark:text-neutral-100"
              >
                URL<span className="text-red-500">*</span>
                <span className="sr-only">(required)</span>
                <CircleAlert className="h-4 w-4 text-neutral-400 dark:text-neutral-500" />
              </label>
              <Input
                id="server-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="Add URL for a running MCP server..."
                className="h-11 rounded-md border-neutral-300 bg-white px-4 text-sm text-neutral-900 shadow-none placeholder:text-neutral-400 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
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
                className="min-h-28 w-full rounded-md border border-neutral-300 bg-white px-4 py-3 text-sm text-neutral-900 shadow-none outline-none transition placeholder:text-neutral-400 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100 dark:placeholder:text-neutral-500"
              />
            </div>

            <div className="flex flex-col gap-5 pt-2">
              <button
                type="button"
                onClick={() => setAdvancedOpen((current) => !current)}
                className="inline-flex w-fit items-center gap-2 text-sm font-medium text-neutral-700 transition hover:text-neutral-950 dark:text-neutral-300 dark:hover:text-neutral-100"
                aria-expanded={advancedOpen}
              >
                <ChevronDown className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`} />
                Advanced options
              </button>

              {advancedOpen && (
                <div className="rounded-md border border-dashed border-neutral-300 bg-neutral-50 px-4 py-3 text-sm text-neutral-600 dark:border-neutral-700 dark:bg-neutral-800/50 dark:text-neutral-400">
                  Additional gateway configuration options can be added here.
                </div>
              )}

              <div className="flex items-center justify-end gap-3 border-t border-neutral-200 pt-6 dark:border-neutral-800">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => handleOpenChange(false)}
                  className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:bg-neutral-800 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:bg-neutral-200"
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
