import { memo, useCallback, useEffect, useId, useMemo, useState } from "react";
import { useIntl } from "react-intl";
import {
  Activity,
  Blocks,
  Bot,
  Box,
  CircleSlash,
  Code,
  MessageSquareCode,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { createVirtualServer, updateVirtualServer } from "@/api/virtualServers";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { CreateServerForm } from "@/components/gateways/CreateServerForm";
import { SourceSelection } from "@/components/gateways/SourceSelection";
import type { ActionCard, CreateServerDetails } from "@/components/gateways/types";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Checkbox } from "@/components/ui/checkbox";
import { Loading } from "@/components/ui/loading";
import { api, ApiError } from "@/api/client";
import { useQuery } from "@/hooks/useQuery";
import { useRouter } from "@/router";
import type { MCPServer, ServerStatus, VirtualServer, VirtualServerTag } from "@/types/server";

const SERVERS_FORM_PATH = "/app/servers?openForm=true";
const EDIT_SERVER_ID_QUERY_PARAM = "editServerId";
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

interface MCPServersResponse {
  gateways?: ListedMCPServer[];
  nextCursor?: string | null;
}

type ComponentKind = "tools" | "resources" | "prompts";

interface ComponentSelection {
  tools: string[];
  resources: string[];
  prompts: string[];
}

type SelectableComponent = (GatewayTool | GatewayResource | GatewayPrompt) & {
  kind: ComponentKind;
};

function getResponseItems<T>(data: T[] | Record<string, unknown> | undefined, key: string): T[] {
  if (Array.isArray(data)) return data;

  const keyedItems = data?.[key];
  if (Array.isArray(keyedItems)) return keyedItems as T[];

  const paginatedItems = data?.items;
  if (Array.isArray(paginatedItems)) return paginatedItems as T[];

  const dataItems = data?.data;
  return Array.isArray(dataItems) ? (dataItems as T[]) : [];
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

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value))));
}

function getComponentName(component: GatewayTool | GatewayResource | GatewayPrompt) {
  return component.name || ("uri" in component ? component.uri : undefined) || component.id;
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

function readEditServerIdFromPath(path: string): string | null {
  const queryIndex = path.indexOf("?");
  if (queryIndex === -1) return null;

  try {
    const params = new URLSearchParams(path.slice(queryIndex + 1));
    const editServerId = params.get(EDIT_SERVER_ID_QUERY_PARAM)?.trim();
    return editServerId || null;
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

async function getComponentsForSelectedMCPServers(
  mcpServerIds: string[],
): Promise<ComponentSelection> {
  const componentGroups = await Promise.all(
    mcpServerIds.map(async (serverId) => {
      const encodedServerId = encodeURIComponent(serverId);
      const [toolsData, resourcesData, promptsData] = await Promise.all([
        api.get<GatewayTool[] | { tools: GatewayTool[] }>(
          `/tools?limit=1000&include_inactive=true&gateway_id=${encodedServerId}`,
        ),
        api.get<GatewayResource[] | { resources: GatewayResource[] }>(
          `/resources?limit=1000&include_inactive=true&gateway_id=${encodedServerId}`,
        ),
        api.get<GatewayPrompt[] | { prompts: GatewayPrompt[] }>(
          `/prompts?limit=1000&include_inactive=true&gateway_id=${encodedServerId}`,
        ),
      ]);

      return {
        tools: getResponseItems(toolsData, "tools").map((tool) => tool.id),
        resources: getResponseItems(resourcesData, "resources").map((resource) => resource.id),
        prompts: getResponseItems(promptsData, "prompts").map((prompt) => prompt.id),
      };
    }),
  );

  return {
    tools: uniqueStrings(componentGroups.flatMap((group) => group.tools)),
    resources: uniqueStrings(componentGroups.flatMap((group) => group.resources)),
    prompts: uniqueStrings(componentGroups.flatMap((group) => group.prompts)),
  };
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

function ComponentCount({
  icon: Icon,
  label,
  count,
}: {
  icon: typeof Wrench;
  label: string;
  count: number;
}) {
  return (
    <span className="flex items-center gap-1.5 text-muted-foreground" aria-label={label}>
      <Icon className="size-3.5" aria-hidden="true" />
      <span aria-hidden="true">{count}</span>
    </span>
  );
}

function ComponentCheckboxRow({
  component,
  checked,
  onComponentSelectionChange,
}: {
  component: SelectableComponent;
  checked: boolean;
  onComponentSelectionChange: (kind: ComponentKind, componentId: string, checked: boolean) => void;
}) {
  const label = getComponentName(component);

  return (
    <label className="flex min-w-0 cursor-pointer items-center gap-3 rounded-sm px-2 py-2 hover:bg-muted/40">
      <Checkbox
        checked={checked}
        onCheckedChange={(nextChecked) =>
          onComponentSelectionChange(component.kind, component.id, nextChecked === true)
        }
        aria-label={`Select ${label}`}
      />
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{label}</span>
    </label>
  );
}

function ComponentGroup({
  title,
  components,
  selectedIds,
  onComponentSelectionChange,
}: {
  title: string;
  components: SelectableComponent[];
  selectedIds: Set<string>;
  onComponentSelectionChange: (kind: ComponentKind, componentId: string, checked: boolean) => void;
}) {
  if (components.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-normal text-muted-foreground">
        {title}
      </h3>
      <div className="divide-y divide-border/60 rounded-md border border-border/60">
        {components.map((component) => (
          <ComponentCheckboxRow
            key={`${component.kind}-${component.id}`}
            component={component}
            checked={selectedIds.has(component.id)}
            onComponentSelectionChange={onComponentSelectionChange}
          />
        ))}
      </div>
    </div>
  );
}

const MCPServerAccordionItem = memo(function MCPServerAccordionItem({
  server,
  isOpen,
  selectedToolIds,
  selectedResourceIds,
  selectedPromptIds,
  onComponentSelectionChange,
}: {
  server: ListedMCPServer;
  isOpen: boolean;
  selectedToolIds: Set<string>;
  selectedResourceIds: Set<string>;
  selectedPromptIds: Set<string>;
  onComponentSelectionChange: (kind: ComponentKind, componentId: string, checked: boolean) => void;
}) {
  const intl = useIntl();
  const {
    data: toolsData,
    error: toolsError,
    isLoading: toolsLoading,
  } = useQuery<GatewayTool[] | { tools: GatewayTool[] }>(
    `/tools?limit=1000&include_inactive=true&gateway_id=${encodeURIComponent(server.id)}`,
    { enabled: isOpen },
  );
  const {
    data: resourcesData,
    error: resourcesError,
    isLoading: resourcesLoading,
  } = useQuery<GatewayResource[] | { resources: GatewayResource[] }>(
    `/resources?limit=1000&include_inactive=true&gateway_id=${encodeURIComponent(server.id)}`,
    { enabled: isOpen },
  );
  const {
    data: promptsData,
    error: promptsError,
    isLoading: promptsLoading,
  } = useQuery<GatewayPrompt[] | { prompts: GatewayPrompt[] }>(
    `/prompts?limit=1000&include_inactive=true&gateway_id=${encodeURIComponent(server.id)}`,
    { enabled: isOpen },
  );

  const status = getStatusConfig(getServerStatus(server));
  const StatusIcon = status.Icon;
  const tools = useMemo(
    () =>
      getResponseItems(toolsData, "tools").map(
        (tool): SelectableComponent => ({ ...tool, kind: "tools" }),
      ),
    [toolsData],
  );
  const resources = useMemo(
    () =>
      getResponseItems(resourcesData, "resources").map(
        (resource): SelectableComponent => ({ ...resource, kind: "resources" }),
      ),
    [resourcesData],
  );
  const prompts = useMemo(
    () =>
      getResponseItems(promptsData, "prompts").map(
        (prompt): SelectableComponent => ({ ...prompt, kind: "prompts" }),
      ),
    [promptsData],
  );
  const isLoadingComponents = toolsLoading || resourcesLoading || promptsLoading;
  const componentError = toolsError ?? resourcesError ?? promptsError;
  const hasComponents = tools.length + resources.length + prompts.length > 0;

  return (
    <AccordionItem value={server.id} className="rounded-md border border-border/60 px-3">
      <AccordionTrigger className="gap-3 py-3 text-left hover:no-underline">
        <span className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <MCPIcon className="size-4 [&_path]:fill-current" />
          </span>
          <span className="min-w-0 flex-1 truncate font-medium text-foreground">{server.name}</span>
          <span className="hidden shrink-0 items-center gap-3 sm:flex">
            <ComponentCount
              icon={Wrench}
              label={intl.formatMessage(
                { id: "gateways.card.toolCount" },
                { count: getToolCount(server) },
              )}
              count={getToolCount(server)}
            />
            <ComponentCount
              icon={Box}
              label={intl.formatMessage(
                { id: "gateways.card.resourceCount" },
                { count: getResourceCount(server) },
              )}
              count={getResourceCount(server)}
            />
            <ComponentCount
              icon={MessageSquareCode}
              label={intl.formatMessage(
                { id: "gateways.card.promptCount" },
                { count: getPromptCount(server) },
              )}
              count={getPromptCount(server)}
            />
          </span>
          <span className="hidden shrink-0 items-center gap-2 text-muted-foreground md:flex">
            <StatusIcon className={`size-3.5 ${status.className}`} aria-hidden="true" />
            {intl.formatMessage({ id: status.labelId })}
          </span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 text-xs sm:hidden">
          <ComponentCount
            icon={Wrench}
            label={intl.formatMessage(
              { id: "gateways.card.toolCount" },
              { count: getToolCount(server) },
            )}
            count={getToolCount(server)}
          />
          <ComponentCount
            icon={Box}
            label={intl.formatMessage(
              { id: "gateways.card.resourceCount" },
              { count: getResourceCount(server) },
            )}
            count={getResourceCount(server)}
          />
          <ComponentCount
            icon={MessageSquareCode}
            label={intl.formatMessage(
              { id: "gateways.card.promptCount" },
              { count: getPromptCount(server) },
            )}
            count={getPromptCount(server)}
          />
        </div>

        {isLoadingComponents && (
          <SourcesLoadingStatus message={intl.formatMessage({ id: "common.loading" })} />
        )}

        {!isLoadingComponents && componentError && (
          <p
            role="alert"
            className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {componentError.message}
          </p>
        )}

        {!isLoadingComponents && !componentError && !hasComponents && (
          <p className="rounded-md border border-border/60 px-3 py-6 text-center text-sm text-muted-foreground">
            {intl.formatMessage({ id: "gateways.details.noComponentsFound" })}
          </p>
        )}

        {!isLoadingComponents && !componentError && hasComponents && (
          <div className="grid gap-4">
            <ComponentGroup
              title={intl.formatMessage({ id: "gateways.details.filter.tools" })}
              components={tools}
              selectedIds={selectedToolIds}
              onComponentSelectionChange={onComponentSelectionChange}
            />
            <ComponentGroup
              title={intl.formatMessage({ id: "gateways.details.filter.resources" })}
              components={resources}
              selectedIds={selectedResourceIds}
              onComponentSelectionChange={onComponentSelectionChange}
            />
            <ComponentGroup
              title={intl.formatMessage({ id: "gateways.details.filter.prompts" })}
              components={prompts}
              selectedIds={selectedPromptIds}
              onComponentSelectionChange={onComponentSelectionChange}
            />
          </div>
        )}
      </AccordionContent>
    </AccordionItem>
  );
});

function EditMCPServersSection({
  selectedToolIds,
  selectedResourceIds,
  selectedPromptIds,
  onComponentSelectionChange,
}: {
  selectedToolIds: string[];
  selectedResourceIds: string[];
  selectedPromptIds: string[];
  onComponentSelectionChange: (kind: ComponentKind, componentId: string, checked: boolean) => void;
}) {
  const intl = useIntl();
  const headingId = useId();
  const [openServerIds, setOpenServerIds] = useState<string[]>([]);
  const {
    data: mcpServersData,
    error: mcpServersError,
    isLoading: mcpServersLoading,
  } = useQuery<MCPServersResponse | ListedMCPServer[]>(MCP_SERVERS_QUERY_PATH);
  const mcpServers = useMemo(() => getMCPServers(mcpServersData), [mcpServersData]);
  const openServerIdSet = useMemo(() => new Set(openServerIds), [openServerIds]);
  const selectedToolIdSet = useMemo(() => new Set(selectedToolIds), [selectedToolIds]);
  const selectedResourceIdSet = useMemo(() => new Set(selectedResourceIds), [selectedResourceIds]);
  const selectedPromptIdSet = useMemo(() => new Set(selectedPromptIds), [selectedPromptIds]);
  const isLoadingSources = mcpServersLoading;
  const loadingSourcesMessage = intl.formatMessage({ id: "gateways.source.loadingSources" });

  return (
    <section
      aria-labelledby={headingId}
      className="border-t border-border pt-7 dark:border-[#2b2b2f]"
    >
      <div className="flex items-center gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-foreground dark:bg-[#252529]">
          <MCPIcon className="size-5 [&_path]:fill-current" />
        </span>
        <h2 id={headingId} className="text-sm font-semibold text-foreground">
          {intl.formatMessage({ id: "gateways.editServer.mcpServers" })}
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

      {!isLoadingSources && !mcpServersError && mcpServers.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {intl.formatMessage({ id: "gateways.editServer.noMCPServers" })}
        </p>
      )}

      {!isLoadingSources && !mcpServersError && mcpServers.length > 0 && (
        <Accordion
          type="multiple"
          value={openServerIds}
          onValueChange={setOpenServerIds}
          className="mt-5 space-y-3"
        >
          {mcpServers.map((server) => (
            <MCPServerAccordionItem
              key={server.id}
              server={server}
              isOpen={openServerIdSet.has(server.id)}
              selectedToolIds={selectedToolIdSet}
              selectedResourceIds={selectedResourceIdSet}
              selectedPromptIds={selectedPromptIdSet}
              onComponentSelectionChange={onComponentSelectionChange}
            />
          ))}
        </Accordion>
      )}
    </section>
  );
}

export function CreateServer() {
  const intl = useIntl();
  const { navigate, path } = useRouter();
  const editServerId = useMemo(() => readEditServerIdFromPath(path), [path]);
  const [step, setStep] = useState<CreateServerStep>("details");
  const [serverDetails, setServerDetails] = useState<CreateServerDetails | null>(null);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [selectedComponents, setSelectedComponents] = useState<ComponentSelection>({
    tools: [],
    resources: [],
    prompts: [],
  });
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const isEditMode = Boolean(editServerId);
  const editServerPath = editServerId ? `/servers/${encodeURIComponent(editServerId)}` : null;
  const {
    data: editingServer,
    error: editServerError,
    isLoading: editServerLoading,
  } = useQuery<VirtualServer>(editServerPath, {
    enabled: Boolean(editServerPath),
  });
  const initialComponentSelection = useMemo(
    (): ComponentSelection => ({
      tools: uniqueStrings(editingServer?.associatedToolIds ?? []),
      resources: uniqueStrings(editingServer?.associatedResources ?? []),
      prompts: uniqueStrings(editingServer?.associatedPrompts ?? []),
    }),
    [
      editingServer?.associatedPrompts,
      editingServer?.associatedResources,
      editingServer?.associatedToolIds,
    ],
  );

  useEffect(() => {
    if (!editingServer?.id) return;
    setSelectedComponents(initialComponentSelection);
  }, [editingServer?.id, initialComponentSelection]);

  const handleComponentSelectionChange = useCallback(
    (kind: ComponentKind, componentId: string, checked: boolean) => {
      setSelectedComponents((current) => {
        const nextIds = new Set(current[kind]);
        if (checked) nextIds.add(componentId);
        else nextIds.delete(componentId);
        return {
          ...current,
          [kind]: Array.from(nextIds),
        };
      });
    },
    [],
  );

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
      const selectedSourceComponents =
        selectedSourceIds.length > 0
          ? await getComponentsForSelectedMCPServers(selectedSourceIds)
          : null;
      const detailsWithSources = {
        ...serverDetails,
        ...(selectedSourceComponents
          ? {
              associatedTools: uniqueStrings([
                ...(serverDetails.associatedTools ?? []),
                ...selectedSourceComponents.tools,
              ]),
              associatedResources: uniqueStrings([
                ...(serverDetails.associatedResources ?? []),
                ...selectedSourceComponents.resources,
              ]),
              associatedPrompts: uniqueStrings([
                ...(serverDetails.associatedPrompts ?? []),
                ...selectedSourceComponents.prompts,
              ]),
            }
          : {}),
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
      const detailsForUpdate = {
        ...details,
        associatedTools: selectedComponents.tools,
        associatedResources: selectedComponents.resources,
        associatedPrompts: selectedComponents.prompts,
      };

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
              selectedToolIds={selectedComponents.tools}
              selectedResourceIds={selectedComponents.resources}
              selectedPromptIds={selectedComponents.prompts}
              onComponentSelectionChange={handleComponentSelectionChange}
            />
          )}
        </CreateServerForm>
      </div>
    </main>
  );
}
