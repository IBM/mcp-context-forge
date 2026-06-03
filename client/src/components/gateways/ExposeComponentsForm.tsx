import { useState, useMemo, useCallback } from "react";
import {
  ChevronDown,
  ChevronRight,
  Wrench,
  Box,
  MessageSquareCode,
  Info,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@/hooks/useQuery";
import { Loading } from "@/components/ui/loading";
import { createVirtualServer } from "@/api/virtualServers";
import { useRouter } from "@/router";
import type { CreateServerDetails } from "@/components/gateways/types";
import type { Visibility } from "@/types/server";

interface ExposeComponentsFormProps {
  gatewayId: string;
  gatewayName: string;
  visibility?: Visibility;
  teamId?: string;
  oauthNotification?: {
    type: "success" | "error";
    message: string;
  } | null;
  clearOAuthNotification?: () => void;
}

interface Tool {
  id: string;
  name: string;
  displayName?: string;
  originalName?: string;
  gatewayId?: string;
}

interface Resource {
  id: string;
  name: string;
  displayName?: string;
  gatewayId?: string;
}

interface Prompt {
  id: string;
  name: string;
  displayName?: string;
  gatewayId?: string;
}

type ToolsResponse = Tool[];
type ResourcesResponse = Resource[];
type PromptsResponse = Prompt[];

interface MCPObjectsTableProps {
  items: Array<{ id: string; name: string; displayName?: string; originalName?: string }>;
  selectedItems: Set<string>;
  allSelected: boolean;
  someSelected: boolean;
  onToggleAll: (checked: boolean) => void;
  onToggleItem: (id: string, checked: boolean) => void;
}

function MCPObjectsTable({
  items,
  selectedItems,
  allSelected,
  someSelected,
  onToggleAll,
  onToggleItem,
}: MCPObjectsTableProps) {
  return (
    <div className="px-6 pb-6 pt-4">
      <Table>
        <TableHeader className="[&_tr]:border-0">
          <TableRow className="border-0 hover:bg-transparent">
            <TableHead className="h-8 w-12 px-2">
              <Checkbox
                checked={allSelected}
                onCheckedChange={onToggleAll}
                aria-label="Select all"
                className={someSelected ? "data-[state=checked]:bg-neutral-600" : ""}
              />
            </TableHead>
            <TableHead className="h-8 px-2 text-neutral-600 dark:text-neutral-400">Name</TableHead>
            <TableHead className="h-8 px-2 text-neutral-600 dark:text-neutral-400">
              Identifier
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className="[&_tr:last-child]:border-0">
          {items.map((item) => (
            <TableRow
              key={item.id}
              className="border-0 hover:bg-neutral-200/30 dark:hover:bg-neutral-800/30"
            >
              <TableCell className="p-2">
                <Checkbox
                  checked={selectedItems.has(item.id)}
                  onCheckedChange={(checked) => onToggleItem(item.id, checked as boolean)}
                  aria-label={`Select ${item.displayName || item.name}`}
                />
              </TableCell>
              <TableCell className="p-2 text-sm text-neutral-950 dark:text-neutral-50">
                {item.displayName || (item as Tool).originalName || item.name}
              </TableCell>
              <TableCell className="p-2 text-sm font-mono text-neutral-600 dark:text-neutral-400">
                {item.name}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function ExposeComponentsForm({
  gatewayId,
  gatewayName,
  visibility = "public",
  teamId,
  oauthNotification,
  clearOAuthNotification,
}: ExposeComponentsFormProps) {
  const { navigate } = useRouter();
  const [expandedSection, setExpandedSection] = useState<string | null>("tools");
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [selectedResources, setSelectedResources] = useState<Set<string>>(new Set());
  const [selectedPrompts, setSelectedPrompts] = useState<Set<string>>(new Set());
  const [requireOAuth, setRequireOAuth] = useState<boolean>(false);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const handleSkip = () => {
    navigate("/app/gateways");
  };

  // Fetch tools, resources, and prompts for this gateway
  const { data: toolsData, isLoading: toolsLoading } = useQuery<ToolsResponse>(
    `/tools?limit=1000&gateway_id=${gatewayId}`,
  );
  const { data: resourcesData, isLoading: resourcesLoading } = useQuery<ResourcesResponse>(
    `/resources?limit=1000&gateway_id=${gatewayId}`,
  );
  const { data: promptsData, isLoading: promptsLoading } = useQuery<PromptsResponse>(
    `/prompts?limit=1000&gateway_id=${gatewayId}`,
  );

  const tools = useMemo(() => (Array.isArray(toolsData) ? toolsData : []), [toolsData]);
  const resources = useMemo(
    () => (Array.isArray(resourcesData) ? resourcesData : []),
    [resourcesData],
  );
  const prompts = useMemo(() => (Array.isArray(promptsData) ? promptsData : []), [promptsData]);

  const toolCount = tools.length;
  const resourceCount = resources.length;
  const promptCount = prompts.length;

  const isLoading = toolsLoading || resourcesLoading || promptsLoading;

  const toggleSection = useCallback((section: string) => {
    setExpandedSection((prev) => (prev === section ? null : section));
  }, []);

  const toggleAllTools = useCallback(
    (checked: boolean) => {
      setSelectedTools(checked ? new Set(tools.map((t) => t.id)) : new Set());
    },
    [tools],
  );

  const toggleTool = useCallback((toolId: string, checked: boolean) => {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (checked) next.add(toolId);
      else next.delete(toolId);
      return next;
    });
  }, []);

  const toggleAllResources = useCallback(
    (checked: boolean) => {
      setSelectedResources(checked ? new Set(resources.map((r) => r.id)) : new Set());
    },
    [resources],
  );

  const toggleResource = useCallback((resourceId: string, checked: boolean) => {
    setSelectedResources((prev) => {
      const next = new Set(prev);
      if (checked) next.add(resourceId);
      else next.delete(resourceId);
      return next;
    });
  }, []);

  const toggleAllPrompts = useCallback(
    (checked: boolean) => {
      setSelectedPrompts(checked ? new Set(prompts.map((p) => p.id)) : new Set());
    },
    [prompts],
  );

  const togglePrompt = useCallback((promptId: string, checked: boolean) => {
    setSelectedPrompts((prev) => {
      const next = new Set(prev);
      if (checked) next.add(promptId);
      else next.delete(promptId);
      return next;
    });
  }, []);

  const handleExposeComponents = async () => {
    setIsCreating(true);
    setCreateError(null);

    try {
      const serverDetails: CreateServerDetails = {
        name: gatewayName,
        visibility,
        teamId,
        oauthEnabled: requireOAuth,
        tags: [],
        description: undefined,
        associatedTools: Array.from(selectedTools),
        associatedResources: Array.from(selectedResources),
        associatedPrompts: Array.from(selectedPrompts),
      };

      await createVirtualServer(serverDetails);
      navigate("/app/gateways");
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "Failed to create virtual server";
      setCreateError(errorMessage);
    } finally {
      setIsCreating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="mx-auto mt-6 w-full max-w-5xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
        <div className="flex items-center justify-center p-12">
          <Loading />
        </div>
      </div>
    );
  }

  const allToolsSelected = tools.length > 0 && selectedTools.size === tools.length;
  const someToolsSelected = selectedTools.size > 0 && selectedTools.size < tools.length;

  const allResourcesSelected = resources.length > 0 && selectedResources.size === resources.length;
  const someResourcesSelected =
    selectedResources.size > 0 && selectedResources.size < resources.length;

  const allPromptsSelected = prompts.length > 0 && selectedPrompts.size === prompts.length;
  const somePromptsSelected = selectedPrompts.size > 0 && selectedPrompts.size < prompts.length;

  return (
    <div className="mx-auto mt-6 w-full max-w-5xl rounded-xl border border-neutral-200 bg-inherit p-0 shadow-[0_12px_40px_rgba(15,23,42,0.12)] dark:border-neutral-800">
      <div className="flex flex-col gap-8 p-6 sm:p-8">
        {/* OAuth notification */}
        {oauthNotification && (
          <div
            role={oauthNotification.type === "error" ? "alert" : "status"}
            className={`flex items-start justify-between rounded-md border p-3 ${
              oauthNotification.type === "success"
                ? "border-green-200 bg-green-50 dark:border-green-900/50 dark:bg-green-950/50"
                : "border-red-200 bg-red-50 dark:border-red-900/50 dark:bg-red-950/50"
            }`}
          >
            <p
              className={`text-sm ${
                oauthNotification.type === "success"
                  ? "text-green-700 dark:text-green-300"
                  : "text-red-600 dark:text-red-400"
              }`}
            >
              {oauthNotification.message}
            </p>
            {clearOAuthNotification && (
              <button
                type="button"
                onClick={clearOAuthNotification}
                aria-label="Dismiss notification"
                className="ml-2 shrink-0 p-1 opacity-60 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500"
              >
                ×
              </button>
            )}
          </div>
        )}

        {/* Main content */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-purple-500 text-neutral-950 shadow-sm">
              <Server className="h-4 w-4" aria-hidden="true" />
            </div>
            <h2 className="text-lg font-semibold tracking-tight text-neutral-950 dark:text-neutral-50">
              Expose MCP tools, resources, and prompts
            </h2>
          </div>

          <p className="text-sm leading-6 text-neutral-600 dark:text-neutral-400">
            ContextForge will create an endpoint that exposes selected components to AI clients as a{" "}
            <span className="font-medium text-cyan-700 dark:text-cyan-400">virtual server</span>.
          </p>
        </div>

        {/* Component sections */}
        <div className="space-y-4">
          {/* Tools section */}
          <div className="rounded-2xl border border-neutral-800 bg-inherit dark:border-neutral-800">
            <Button
              type="button"
              variant="ghost"
              onClick={() => toggleSection("tools")}
              aria-expanded={expandedSection === "tools"}
              aria-controls="tools-region"
              className="flex h-auto w-full items-center justify-between rounded-2xl px-6 py-4 text-left hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50"
            >
              <div className="flex items-center gap-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-neutral-800 dark:bg-neutral-800">
                  <Wrench
                    className="h-4 w-4 text-neutral-300 dark:text-neutral-300"
                    aria-hidden="true"
                  />
                </div>
                <span className="text-base font-normal text-neutral-600 dark:text-neutral-400">
                  {toolCount} {toolCount === 1 ? "tool" : "tools"}
                </span>
              </div>
              {expandedSection === "tools" ? (
                <ChevronDown
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              ) : (
                <ChevronRight
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              )}
            </Button>

            {expandedSection === "tools" && tools.length > 0 && (
              <div id="tools-region" role="region" aria-label="Tools">
                <MCPObjectsTable
                  items={tools}
                  selectedItems={selectedTools}
                  allSelected={allToolsSelected}
                  someSelected={someToolsSelected}
                  onToggleAll={toggleAllTools}
                  onToggleItem={toggleTool}
                />
              </div>
            )}
          </div>

          {/* Resources section */}
          <div className="rounded-2xl border border-neutral-800 bg-inherit dark:border-neutral-800">
            <Button
              type="button"
              variant="ghost"
              onClick={() => toggleSection("resources")}
              aria-expanded={expandedSection === "resources"}
              aria-controls="resources-region"
              className="flex h-auto w-full items-center justify-between rounded-2xl px-6 py-4 text-left hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50"
            >
              <div className="flex items-center gap-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-neutral-800 dark:bg-neutral-800">
                  <Box
                    className="h-4 w-4 text-neutral-300 dark:text-neutral-300"
                    aria-hidden="true"
                  />
                </div>
                <span className="text-base font-normal text-neutral-600 dark:text-neutral-400">
                  {resourceCount} {resourceCount === 1 ? "resource" : "resources"}
                </span>
              </div>
              {expandedSection === "resources" ? (
                <ChevronDown
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              ) : (
                <ChevronRight
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              )}
            </Button>
            {expandedSection === "resources" && resources.length > 0 && (
              <div id="resources-region" role="region" aria-label="Resources">
                <MCPObjectsTable
                  items={resources}
                  selectedItems={selectedResources}
                  allSelected={allResourcesSelected}
                  someSelected={someResourcesSelected}
                  onToggleAll={toggleAllResources}
                  onToggleItem={toggleResource}
                />
              </div>
            )}
          </div>

          {/* Prompts section */}
          <div className="rounded-2xl border border-neutral-800 bg-inherit dark:border-neutral-800">
            <Button
              type="button"
              variant="ghost"
              onClick={() => toggleSection("prompts")}
              aria-expanded={expandedSection === "prompts"}
              aria-controls="prompts-region"
              className="flex h-auto w-full items-center justify-between rounded-2xl px-6 py-4 text-left hover:bg-neutral-200/50 dark:hover:bg-neutral-800/50"
            >
              <div className="flex items-center gap-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-neutral-800 dark:bg-neutral-800">
                  <MessageSquareCode
                    className="h-4 w-4 text-neutral-300 dark:text-neutral-300"
                    aria-hidden="true"
                  />
                </div>
                <span className="text-base font-normal text-neutral-600 dark:text-neutral-400">
                  {promptCount} prompt {promptCount === 1 ? "template" : "templates"}
                </span>
              </div>
              {expandedSection === "prompts" ? (
                <ChevronDown
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              ) : (
                <ChevronRight
                  className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
                  aria-hidden="true"
                />
              )}
            </Button>
            {expandedSection === "prompts" && prompts.length > 0 && (
              <div id="prompts-region" role="region" aria-label="Prompt templates">
                <MCPObjectsTable
                  items={prompts}
                  selectedItems={selectedPrompts}
                  allSelected={allPromptsSelected}
                  someSelected={somePromptsSelected}
                  onToggleAll={toggleAllPrompts}
                  onToggleItem={togglePrompt}
                />
              </div>
            )}
          </div>
        </div>

        {/* OAuth section */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-medium text-neutral-950 dark:text-neutral-50">
              Require OAuth for inbound clients
            </h3>
            <Info
              className="h-4 w-4 text-neutral-500 dark:text-neutral-500"
              aria-label="OAuth information"
            />
          </div>
          <div className="flex items-start gap-3">
            <Switch
              id="oauth-toggle"
              checked={requireOAuth}
              onCheckedChange={setRequireOAuth}
              aria-label="Require OAuth for inbound clients"
            />
            <Label
              htmlFor="oauth-toggle"
              className="text-sm font-normal leading-relaxed text-neutral-600 dark:text-neutral-400 cursor-pointer"
            >
              Reject unauthenticated requests and expose RFC 9728 metadata for OAuth-aware clients
            </Label>
          </div>
        </div>

        {/* Error message */}
        {createError && (
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/50 dark:bg-red-950/50"
          >
            <p className="text-sm text-red-600 dark:text-red-400">{createError}</p>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex items-center justify-end gap-3 pt-6">
          <Button
            type="button"
            variant="ghost"
            onClick={handleSkip}
            disabled={isCreating}
            className="h-10 rounded-md px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-100 hover:text-neutral-950 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
          >
            Skip
          </Button>
          <Button
            type="button"
            onClick={handleExposeComponents}
            disabled={isCreating}
            className="h-10 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:enabled:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:enabled:bg-neutral-200"
          >
            {isCreating ? "Creating..." : "Expose components"}
          </Button>
        </div>
      </div>
    </div>
  );
}
