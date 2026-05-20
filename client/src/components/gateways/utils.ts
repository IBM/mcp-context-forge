import type { VirtualServer, VirtualServerTag } from "@/types/server";
import type { DetailComponentItem } from "@/components/gateways/types";

export function formatServerTimestamp(value?: string) {
  if (!value) return "Not synced yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function formatServerDateTime(value?: string) {
  return formatServerTimestamp(value);
}

export function formatVisibility(value?: string) {
  if (!value) return "N/A";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function truncateMiddle(value: string, maxLength = 24) {
  if (value.length <= maxLength) return value;
  const edgeLength = Math.max(4, Math.floor((maxLength - 3) / 2));
  return `${value.slice(0, edgeLength)}...${value.slice(-edgeLength)}`;
}

export function getVirtualServerEndpoint(serverId: string) {
  const encodedServerId = encodeURIComponent(serverId);
  if (typeof window === "undefined" || !window.location?.origin) {
    return `/servers/${encodedServerId}/mcp`;
  }
  return `${window.location.origin}/servers/${encodedServerId}/mcp`;
}

export function copyToClipboard(value: string) {
  void navigator.clipboard?.writeText(value);
}

export function getTagDisplay(tag: string | VirtualServerTag, index: number) {
  if (typeof tag === "string") {
    return { key: `${tag}-${index}`, label: tag };
  }

  const label = tag.label ?? tag.name ?? tag.value ?? tag.id ?? "Tag";
  return { key: `${tag.id ?? label}-${index}`, label };
}

export function getComponentLabel(type: DetailComponentItem["type"]) {
  if (type === "tools") return "tool";
  if (type === "resources") return "resource";
  return "prompt";
}

export function buildComponentItems(server: VirtualServer): DetailComponentItem[] {
  const toolNames = server.associatedTools ?? [];
  const toolIds = server.associatedToolIds ?? [];
  const toolItems = (toolIds.length > 0 ? toolIds : toolNames).map((idOrName, index) => {
    const name = toolNames[index] ?? idOrName;
    const secondary = toolIds[index] && toolIds[index] !== name ? toolIds[index] : undefined;
    return {
      id: `tool-${idOrName}-${index}`,
      name,
      secondary,
      type: "tools" as const,
    };
  });

  const resourceItems = (server.associatedResources ?? []).map((resource, index) => ({
    id: `resource-${resource}-${index}`,
    name: resource,
    type: "resources" as const,
  }));

  const promptItems = (server.associatedPrompts ?? []).map((prompt, index) => ({
    id: `prompt-${prompt}-${index}`,
    name: prompt,
    type: "prompts" as const,
  }));

  return [...toolItems, ...resourceItems, ...promptItems];
}
