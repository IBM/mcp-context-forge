import { useEffect, useId, useMemo, useState } from "react";
import { useIntl } from "react-intl";
import {
  Activity,
  Blocks,
  Bot,
  Box,
  CircleSlash,
  Code,
  MessageSquareCode,
  Server,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { createVirtualServer, updateVirtualServer } from "@/api/virtualServers";
import { api } from "@/api/client";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { CreateServerForm } from "@/components/gateways/CreateServerForm";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard, CreateServerDetails } from "@/components/gateways/types";
import { Checkbox } from "@/components/ui/checkbox";
import { Loading } from "@/components/ui/loading";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError } from "@/api/client";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { MCPServer, ServerStatus, VirtualServer, VirtualServerTag } from "@/types/server";

const SERVERS_FORM_PATH = "/app/servers?openForm=true";
const EDIT_SERVER_STORAGE_KEY = "gateways.editServer";
const MCP_SERVERS_QUERY_PATH = "/gateways?limit=100&include_inactive=true";

type CreateServerStep = "details" | "sources";
type ListedMCPServer = MCPServer & {
  tool_count?: number;
  resource_count?: number;
  prompt_count?: number;
};

interface GatewayTool {
  id: string;
  name: string;
  originalName?: string;
  gatewayId?: string;
  gateway_id?: string;
}

interface GatewayResource {
  id: string;
  name: string;
  uri?: string;
  gatewayId?: string;
  gateway_id?: string;
}

interface GatewayPrompt {
  id: string;
  name: string;
  originalName?: string;
  gatewayId?: string;
  gateway_id?: string;
}

interface MCPServerComponents {
  tools: GatewayTool[];
  resources: GatewayResource[];
  prompts: GatewayPrompt[];
}

interface MCPServersResponse {
  gateways?: ListedMCPServer[];
  nextCursor?: string | null;
}

function getResponseItems<T>(data: T[] | Record<string, T[]> | undefined, key: string): T[] {
  if (Array.isArray(data)) return data;
  return data?.[key] ?? [];
}

function getMCPServers(data: MCPServersResponse | ListedMCPServer[] | undefined) {
  if (Array.isArray(data)) return data;
  return data?.gateways ?? [];
}

function getToolCount(server: ListedMCPServer) {
  return server.toolCount ?? server.tool_count ?? 0;
}

function getResourceCount(server: ListedMCPServer) {
  return server.resourceCount ?? server.resource_count ?? 0;
}

function getPromptCount(server: ListedMCPServer) {
  return server.promptCount ?? server.prompt_count ?? 0;
}

function getServerStatus(server: ListedMCPServer): ServerStatus {
  if (!server.enabled) return "draft";
  if (!server.reachable) return server.lastSeen ? "warning" : "offline";
  return "active";
}

function getStatusConfig(status: ServerStatus) {
  switch (status) {
    case "active":
      return {
        Icon: Activity,
        labelId: "gateways.source.status.active",
        className: "text-emerald-400",
      };
    case "warning":
      return {
        Icon: TriangleAlert,
        labelId: "gateways.source.status.warning",
        className: "text-amber-400",
      };
    case "offline":
      return {
        Icon: CircleSlash,
        labelId: "gateways.source.status.offline",
        className: "text-muted-foreground",
      };
    default:
      return {
        Icon: CircleSlash,
        labelId: "gateways.source.status.inactive",
        className: "text-muted-foreground",
      };
  }
}

function getTagValue(tag: string | VirtualServerTag): string | null {
  if (typeof tag === "string") return tag;
  return tag.label ?? tag.name ?? tag.value ?? null;
}

function getComponentGatewayId(component: GatewayTool | GatewayResource | GatewayPrompt) {
  return component.gatewayId ?? component.gateway_id;
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value))));
}

function getRetainedComponentIds<T extends GatewayTool | GatewayResource | GatewayPrompt>(
  components: T[],
  fallbackIds: string[] | undefined,
  removedSourceIds: Set<string>,
  removedComponentIds: Set<string> = new Set(),
) {
  const fetchedIds = new Set(components.map((component) => component.id));
  return uniqueStrings([
    ...components
      .filter((component) => {
        const gatewayId = getComponentGatewayId(component);
        if (removedComponentIds.has(component.id)) return false;
        return !gatewayId || !removedSourceIds.has(gatewayId);
      })
      .map((component) => component.id),
    ...(fallbackIds ?? []).filter((id) => !fetchedIds.has(id) && !removedComponentIds.has(id)),
  ]);
}

async function fetchComponentsForMCPServer(serverId: string): Promise<MCPServerComponents> {
  const encodedServerId = encodeURIComponent(serverId);
  const [toolsResult, resourcesResult, promptsResult] = await Promise.allSettled([
    api.get<GatewayTool[] | { tools: GatewayTool[] }>(
      `/tools?limit=1000&gateway_id=${encodedServerId}`,
    ),
    api.get<GatewayResource[] | { resources: GatewayResource[] }>(
      `/resources?limit=1000&gateway_id=${encodedServerId}`,
    ),
    api.get<GatewayPrompt[] | { prompts: GatewayPrompt[] }>(
      `/prompts?limit=1000&gateway_id=${encodedServerId}`,
    ),
  ]);

  return {
    tools: toolsResult.status === "fulfilled" ? getResponseItems(toolsResult.value, "tools") : [],
    resources:
      resourcesResult.status === "fulfilled"
        ? getResponseItems(resourcesResult.value, "resources")
        : [],
    prompts:
      promptsResult.status === "fulfilled" ? getResponseItems(promptsResult.value, "prompts") : [],
  };
}

function getEditServerInitialValues(server: VirtualServer): CreateServerDetails {
  return {
    name: server.name,
    visibility: server.visibility,
    oauthEnabled: server.oauthEnabled,
    tags: (server.tags ?? []).map(getTagValue).filter((tag): tag is string => Boolean(tag)),
    description: server.description,
    teamId: server.teamId,
  };
}

function readStoredEditServerId(): string | null {
  try {
    const raw = window.sessionStorage.getItem(EDIT_SERVER_STORAGE_KEY);
    if (!raw) return null;
    const trimmed = raw.trim();
    if (!trimmed) return null;

    if (trimmed.startsWith("{")) {
      const parsed = JSON.parse(trimmed) as Partial<VirtualServer>;
      return parsed.id ?? null;
    }

    return trimmed;
  } catch {
    return null;
  }
}

function getCreateServerError(error: unknown, fallbackMessage: string): string {
  if (error instanceof ApiError) {
    const body = error.body as { message?: string; detail?: unknown } | null;
    if (body?.message) return body.message;
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      return body.detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg?: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
  }

  if (error instanceof Error) return error.message;
  return fallbackMessage;
}

function SourcesLoadingStatus({ message }: { message: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-2 py-10 text-muted-foreground"
    >
      <Loading />
      <span>{message}</span>
    </div>
  );
}

function EditMCPServersSection({
  connectedSourceIds,
  removedConnectedSourceIds,
  selectedAvailableSourceIds,
  onRemovedConnectedSourceIdsChange,
  onSelectedAvailableSourceIdsChange,
}: {
  connectedSourceIds: string[];
  removedConnectedSourceIds: string[];
  selectedAvailableSourceIds: string[];
  onRemovedConnectedSourceIdsChange: (sourceIds: string[]) => void;
  onSelectedAvailableSourceIdsChange: (sourceIds: string[]) => void;
}) {
  const intl = useIntl();
  const connectedHeadingId = useId();
  const availableHeadingId = useId();
  const {
    data: mcpServersData,
    error: mcpServersError,
    isLoading: mcpServersLoading,
  } = useQuery<MCPServersResponse | ListedMCPServer[]>(MCP_SERVERS_QUERY_PATH);
  const mcpServers = useMemo(() => getMCPServers(mcpServersData), [mcpServersData]);
  const removedConnectedSourceIdSet = useMemo(
    () => new Set(removedConnectedSourceIds),
    [removedConnectedSourceIds],
  );
  const selectedAvailableSourceIdSet = useMemo(
    () => new Set(selectedAvailableSourceIds),
    [selectedAvailableSourceIds],
  );
  const connectedSourceIdSet = useMemo(() => new Set(connectedSourceIds), [connectedSourceIds]);
  const connectedMCPServers = useMemo(
    () => mcpServers.filter((server) => connectedSourceIdSet.has(server.id)),
    [connectedSourceIdSet, mcpServers],
  );
  const availableMCPServers = useMemo(
    () => mcpServers.filter((server) => !connectedSourceIdSet.has(server.id)),
    [connectedSourceIdSet, mcpServers],
  );

  const toggleConnectedMCPServerSelection = (serverId: string, checked: boolean) => {
    const next = new Set(removedConnectedSourceIdSet);
    if (checked) next.delete(serverId);
    else next.add(serverId);
    onRemovedConnectedSourceIdsChange(Array.from(next));
  };

  const toggleAvailableMCPServerSelection = (serverId: string, checked: boolean) => {
    const next = new Set(selectedAvailableSourceIdSet);
    if (checked) next.add(serverId);
    else next.delete(serverId);
    onSelectedAvailableSourceIdsChange(Array.from(next));
  };

  const renderServerRows = (servers: ListedMCPServer[], listType: "connected" | "available") => (
    <div className="mt-5 overflow-hidden rounded-md border border-border/60">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-9 w-10 px-3">
              <span className="sr-only">
                {intl.formatMessage({ id: "gateways.source.selectColumn" })}
              </span>
            </TableHead>
            <TableHead className="h-9 px-3 text-xs font-medium">
              {intl.formatMessage({ id: "common.name" })}
            </TableHead>
            <TableHead className="h-9 px-3 text-xs font-medium">
              {intl.formatMessage({ id: "navigation.components" })}
            </TableHead>
            <TableHead className="h-9 w-28 px-3 text-xs font-medium">
              {intl.formatMessage({ id: "gateways.details.status" })}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {servers.map((server) => {
            const status = getStatusConfig(getServerStatus(server));
            const StatusIcon = status.Icon;
            const isSelected =
              listType === "connected"
                ? !removedConnectedSourceIdSet.has(server.id)
                : selectedAvailableSourceIdSet.has(server.id);

            return (
              <TableRow
                key={server.id}
                className="min-h-12 hover:bg-muted/30 data-[state=selected]:bg-muted/30"
                data-state={isSelected ? "selected" : undefined}
              >
                <TableCell className="w-10 px-3 py-2">
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={(checked) => {
                      if (listType === "connected") {
                        toggleConnectedMCPServerSelection(server.id, checked === true);
                        return;
                      }
                      toggleAvailableMCPServerSelection(server.id, checked === true);
                    }}
                    aria-label={intl.formatMessage(
                      { id: "gateways.source.selectSource" },
                      { name: server.name },
                    )}
                  />
                </TableCell>
                <TableCell className="min-w-52 px-3 py-2">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
                      <Server className="size-4" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {server.name}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="min-w-44 px-3 py-2">
                  <div className="flex min-w-0 items-center gap-3 text-muted-foreground">
                    <span
                      className="flex items-center gap-1.5"
                      aria-label={intl.formatMessage(
                        { id: "gateways.card.toolCount" },
                        { count: getToolCount(server) },
                      )}
                    >
                      <Wrench className="size-3.5" aria-hidden="true" />
                      <span aria-hidden="true">{getToolCount(server)}</span>
                    </span>
                    <span className="text-border" aria-hidden="true">
                      •
                    </span>
                    <span
                      className="flex items-center gap-1.5"
                      aria-label={intl.formatMessage(
                        { id: "gateways.card.resourceCount" },
                        { count: getResourceCount(server) },
                      )}
                    >
                      <Box className="size-3.5" aria-hidden="true" />
                      <span aria-hidden="true">{getResourceCount(server)}</span>
                    </span>
                    <span className="text-border" aria-hidden="true">
                      •
                    </span>
                    <span
                      className="flex items-center gap-1.5"
                      aria-label={intl.formatMessage(
                        { id: "gateways.card.promptCount" },
                        { count: getPromptCount(server) },
                      )}
                    >
                      <MessageSquareCode className="size-3.5" aria-hidden="true" />
                      <span aria-hidden="true">{getPromptCount(server)}</span>
                    </span>
                  </div>
                </TableCell>
                <TableCell className="w-28 px-3 py-2">
                  <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                    <StatusIcon className={`size-3.5 ${status.className}`} aria-hidden="true" />
                    {intl.formatMessage({ id: status.labelId })}
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
  const isLoadingSources = mcpServersLoading;
  const loadingSourcesMessage = intl.formatMessage({ id: "gateways.source.loadingSources" });

  return (
    <section
      aria-labelledby={connectedHeadingId}
      className="border-t border-border pt-7 dark:border-[#2b2b2f]"
    >
      <div className="flex items-center gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-foreground dark:bg-[#252529]">
          <MCPIcon className="size-5 [&_path]:fill-current" />
        </span>
        <h2 id={connectedHeadingId} className="text-sm font-semibold text-foreground">
          {intl.formatMessage({ id: "gateways.editServer.connectedMCPServers" })}
        </h2>
      </div>

      {isLoadingSources && <SourcesLoadingStatus message={loadingSourcesMessage} />}

      {!isLoadingSources && mcpServersError && (
        <p
          role="alert"
          className="mt-5 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {mcpServersError.message}
        </p>
      )}

      {!isLoadingSources && !mcpServersError && connectedMCPServers.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {intl.formatMessage({ id: "gateways.editServer.noConnectedMCPServers" })}
        </p>
      )}

      {!isLoadingSources &&
        !mcpServersError &&
        connectedMCPServers.length > 0 &&
        renderServerRows(connectedMCPServers, "connected")}

      {!isLoadingSources && !mcpServersError && (
        <section aria-labelledby={availableHeadingId} className="mt-8 border-t border-border pt-5">
          <h3 id={availableHeadingId} className="text-sm font-semibold text-foreground">
            {intl.formatMessage({ id: "gateways.editServer.availableMCPServers" })}
          </h3>

          {availableMCPServers.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {intl.formatMessage({ id: "gateways.editServer.noAvailableMCPServers" })}
            </p>
          ) : (
            renderServerRows(availableMCPServers, "available")
          )}
          {selectedAvailableSourceIds.length > 0 && (
            <p className="mt-3 text-sm text-muted-foreground">
              {intl.formatMessage(
                { id: "gateways.editServer.selectedMCPServers" },
                { count: selectedAvailableSourceIds.length },
              )}
            </p>
          )}
        </section>
      )}
    </section>
  );
}

export function CreateServer() {
  const intl = useIntl();
  const { navigate } = useRouter();
  const [editServerId] = useState<string | null>(() => readStoredEditServerId());
  const [step, setStep] = useState<CreateServerStep>("details");
  const [serverDetails, setServerDetails] = useState<CreateServerDetails | null>(null);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [removedConnectedSourceIds, setRemovedConnectedSourceIds] = useState<string[]>([]);
  const [selectedAvailableSourceIds, setSelectedAvailableSourceIds] = useState<string[]>([]);
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const isEditMode = Boolean(editServerId);
  const encodedEditServerId = encodeURIComponent(editServerId ?? "__pending__");
  const {
    data: editingServer,
    error: editServerError,
    isLoading: editServerLoading,
  } = useQuery<VirtualServer>(`/servers/${encodedEditServerId}`, {
    enabled: isEditMode,
  });
  const editComponentsEnabled = isEditMode && Boolean(editingServer?.id);
  const { data: editToolsData } = useQuery<GatewayTool[] | { tools: GatewayTool[] }>(
    `/servers/${encodedEditServerId}/tools?include_inactive=true`,
    { enabled: editComponentsEnabled },
  );
  const { data: editResourcesData } = useQuery<
    GatewayResource[] | { resources: GatewayResource[] }
  >(`/servers/${encodedEditServerId}/resources?include_inactive=true`, {
    enabled: editComponentsEnabled,
  });
  const { data: editPromptsData } = useQuery<GatewayPrompt[] | { prompts: GatewayPrompt[] }>(
    `/servers/${encodedEditServerId}/prompts?include_inactive=true`,
    { enabled: editComponentsEnabled },
  );
  const existingTools = useMemo(() => getResponseItems(editToolsData, "tools"), [editToolsData]);
  const existingResources = useMemo(
    () => getResponseItems(editResourcesData, "resources"),
    [editResourcesData],
  );
  const existingPrompts = useMemo(
    () => getResponseItems(editPromptsData, "prompts"),
    [editPromptsData],
  );
  const connectedSourceIds = useMemo(
    () =>
      uniqueStrings([
        ...existingTools.map(getComponentGatewayId),
        ...existingResources.map(getComponentGatewayId),
        ...existingPrompts.map(getComponentGatewayId),
      ]),
    [existingPrompts, existingResources, existingTools],
  );
  const existingToolIds = useMemo(
    () =>
      uniqueStrings([
        ...existingTools.map((tool) => tool.id),
        ...(editingServer?.associatedToolIds ?? []),
      ]),
    [editingServer?.associatedToolIds, existingTools],
  );
  const existingResourceIds = useMemo(
    () =>
      uniqueStrings([
        ...existingResources.map((resource) => resource.id),
        ...(editingServer?.associatedResources ?? []),
      ]),
    [editingServer?.associatedResources, existingResources],
  );
  const existingPromptIds = useMemo(
    () =>
      uniqueStrings([
        ...existingPrompts.map((prompt) => prompt.id),
        ...(editingServer?.associatedPrompts ?? []),
      ]),
    [editingServer?.associatedPrompts, existingPrompts],
  );

  useEffect(() => {
    if (!editServerId) return;
    try {
      window.sessionStorage.removeItem(EDIT_SERVER_STORAGE_KEY);
    } catch {
      // Ignore storage cleanup failures; the edit id has already been read.
    }
  }, [editServerId]);

  const actionCards: ActionCard[] = useMemo(
    () => [
      {
        icon: MCPIcon,
        title: intl.formatMessage({ id: "gateways.action.mcpServer.title" }),
        description: intl.formatMessage({ id: "gateways.action.mcpServer.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate(SERVERS_FORM_PATH),
      },
      {
        icon: Bot,
        title: intl.formatMessage({ id: "gateways.action.aiAgent.title" }),
        description: intl.formatMessage({ id: "gateways.action.aiAgent.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        onAction: () => navigate("/app/agents"),
      },
      {
        icon: Code,
        title: intl.formatMessage({ id: "gateways.action.restApi.title" }),
        description: intl.formatMessage({ id: "gateways.action.restApi.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
      {
        icon: Blocks,
        title: intl.formatMessage({ id: "gateways.action.grpc.title" }),
        description: intl.formatMessage({ id: "gateways.action.grpc.description" }),
        buttonText: intl.formatMessage({ id: "gateways.action.connect" }),
        disabled: true,
        disabledReason: intl.formatMessage({ id: "gateways.action.comingSoon" }),
        onAction: () => undefined,
      },
    ],
    [intl, navigate],
  );

  const handleSkipForNow = async () => {
    if (!serverDetails) {
      setStep("details");
      return;
    }

    setIsCreating(true);
    setCreateError(null);
    try {
      const detailsWithSources = {
        ...serverDetails,
        associatedMCPServerIds: selectedSourceIds,
      };
      await createVirtualServer(detailsWithSources);
      navigate("/app/gateways");
    } catch (error) {
      setCreateError(
        getCreateServerError(
          error,
          intl.formatMessage({ id: "gateways.createServer.errorFallback" }),
        ),
      );
    } finally {
      setIsCreating(false);
    }
  };

  const handleUpdateServer = async (details: CreateServerDetails) => {
    if (!editingServer) return;

    setIsUpdating(true);
    setUpdateError(null);
    try {
      let selectedTools: GatewayTool[] = [];
      let selectedResources: GatewayResource[] = [];
      let selectedPrompts: GatewayPrompt[] = [];

      if (selectedAvailableSourceIds.length > 0) {
        const selectedComponents = await Promise.all(
          selectedAvailableSourceIds.map((sourceId) => fetchComponentsForMCPServer(sourceId)),
        );
        selectedTools = selectedComponents.flatMap((components) => components.tools);
        selectedResources = selectedComponents.flatMap((components) => components.resources);
        selectedPrompts = selectedComponents.flatMap((components) => components.prompts);
      }
      const removedComponents =
        removedConnectedSourceIds.length > 0
          ? await Promise.all(
              removedConnectedSourceIds.map((sourceId) => fetchComponentsForMCPServer(sourceId)),
            )
          : [];
      const removedToolIds = new Set(
        removedComponents.flatMap((components) => components.tools.map((tool) => tool.id)),
      );
      const removedResourceIds = new Set(
        removedComponents.flatMap((components) =>
          components.resources.map((resource) => resource.id),
        ),
      );
      const removedPromptIds = new Set(
        removedComponents.flatMap((components) => components.prompts.map((prompt) => prompt.id)),
      );
      const removedSourceIdSet = new Set(removedConnectedSourceIds);
      const detailsForUpdate =
        selectedAvailableSourceIds.length > 0 || removedConnectedSourceIds.length > 0
          ? {
              ...details,
              associatedTools: uniqueStrings([
                ...getRetainedComponentIds(
                  existingTools,
                  existingToolIds,
                  removedSourceIdSet,
                  removedToolIds,
                ),
                ...selectedTools.map((tool) => tool.id),
              ]),
              associatedResources: uniqueStrings([
                ...getRetainedComponentIds(
                  existingResources,
                  existingResourceIds,
                  removedSourceIdSet,
                  removedResourceIds,
                ),
                ...selectedResources.map((resource) => resource.id),
              ]),
              associatedPrompts: uniqueStrings([
                ...getRetainedComponentIds(
                  existingPrompts,
                  existingPromptIds,
                  removedSourceIdSet,
                  removedPromptIds,
                ),
                ...selectedPrompts.map((prompt) => prompt.id),
              ]),
            }
          : details;

      await updateVirtualServer(editingServer.id, detailsForUpdate);
      navigate("/app/gateways");
    } catch (error) {
      setUpdateError(
        getCreateServerError(
          error,
          intl.formatMessage({ id: "gateways.editServer.errorFallback" }),
        ),
      );
    } finally {
      setIsUpdating(false);
    }
  };

  if (!isEditMode && step === "sources") {
    return (
      <main className="bg-background px-6 py-10">
        <SourceSelection
          actionCards={actionCards}
          associatedMCPServerIds={serverDetails?.associatedMCPServerIds}
          onSelectSources={setSelectedSourceIds}
          createServerActions={{
            onBack: () => setStep("details"),
            onSkip: handleSkipForNow,
            isSkipping: isCreating,
            skipError: createError,
          }}
        />
        {serverDetails && (
          <span className="sr-only" aria-live="polite">
            {intl.formatMessage(
              { id: "gateways.createServer.completedLive" },
              { name: serverDetails.name },
            )}
          </span>
        )}
      </main>
    );
  }

  if (isEditMode && editServerLoading) {
    return (
      <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-6 py-10">
        <SourcesLoadingStatus message={intl.formatMessage({ id: "common.loading" })} />
      </main>
    );
  }

  if (isEditMode && (editServerError || !editingServer)) {
    return (
      <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-6 py-10">
        <div
          role="alert"
          className="w-full max-w-[56rem] rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {editServerError?.message ??
            intl.formatMessage({ id: "gateways.editServer.errorFallback" })}
        </div>
      </main>
    );
  }

  const editInitialValues = editingServer ? getEditServerInitialValues(editingServer) : undefined;

  return (
    <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-background px-6 py-10">
      <div className="w-full max-w-[56rem] space-y-5">
        <CreateServerForm
          key={isEditMode ? editingServer?.id : "create-server"}
          initialValues={editInitialValues ?? serverDetails ?? undefined}
          title={isEditMode ? intl.formatMessage({ id: "gateways.editServer.title" }) : undefined}
          description={
            isEditMode ? intl.formatMessage({ id: "gateways.editServer.description" }) : undefined
          }
          submitLabel={
            isEditMode ? intl.formatMessage({ id: "gateways.editServer.submit" }) : undefined
          }
          isSubmitting={isEditMode ? isUpdating : false}
          submitError={isEditMode ? updateError : undefined}
          onCancel={() => navigate("/app/gateways")}
          onSuccess={(details) => {
            if (isEditMode) {
              void handleUpdateServer(details);
              return;
            }
            setServerDetails(details);
            setCreateError(null);
            setStep("sources");
          }}
        >
          {isEditMode && (
            <EditMCPServersSection
              connectedSourceIds={connectedSourceIds}
              removedConnectedSourceIds={removedConnectedSourceIds}
              selectedAvailableSourceIds={selectedAvailableSourceIds}
              onRemovedConnectedSourceIdsChange={setRemovedConnectedSourceIds}
              onSelectedAvailableSourceIdsChange={setSelectedAvailableSourceIds}
            />
          )}
        </CreateServerForm>
      </div>
    </main>
  );
}
