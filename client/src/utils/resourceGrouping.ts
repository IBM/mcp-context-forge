import type { Resource, ResourceGroup } from "@/types/resource";

/**
 * Groups resources by gateway slug and determines active status
 *
 * @param resources - Array of resources to group
 * @returns Sorted array of resource groups (alphabetically by gateway slug)
 *
 * @example
 * ```ts
 * const resources = [
 *   { id: "1", gatewaySlug: "gateway-a", enabled: true, ... },
 *   { id: "2", gatewaySlug: "gateway-a", enabled: false, ... },
 *   { id: "3", gatewaySlug: "gateway-b", enabled: true, ... },
 * ];
 * const groups = groupResourcesByGateway(resources);
 * // Returns: [
 * //   { gatewaySlug: "gateway-a", resources: [...], isActive: true },
 * //   { gatewaySlug: "gateway-b", resources: [...], isActive: true }
 * // ]
 * ```
 */
export function groupResourcesByGateway(resources: Resource[]): ResourceGroup[] {
  const groups = new Map<string, ResourceGroup>();

  for (const resource of resources) {
    const slug = resource.gatewaySlug || "ungrouped";

    // Initialize group if first resource for this gateway
    if (!groups.has(slug)) {
      groups.set(slug, {
        gatewaySlug: slug,
        gatewayId: resource.gatewayId,
        resources: [],
        isActive: false,
      });
    }

    // Add resource and update active status
    const group = groups.get(slug)!;
    group.resources.push(resource);
    if (resource.enabled) {
      group.isActive = true;
    }
  }

  // Sort alphabetically by gateway slug
  return Array.from(groups.values()).sort((a, b) => a.gatewaySlug.localeCompare(b.gatewaySlug));
}
