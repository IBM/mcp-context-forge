import { createContext, useContext, type ReactNode } from "react";
import type { ResourceGroup } from "@/types/resource";

/**
 * Context for sharing resources state across components
 * Reduces prop drilling and centralizes resource management
 */
interface ResourcesContextValue {
  /** Refetch resources from the API */
  refetch: () => Promise<void>;
  /** Currently selected resource group for details panel */
  selectedGroup: ResourceGroup | null;
  /** Update the selected resource group */
  setSelectedGroup: (group: ResourceGroup | null) => void;
}

const ResourcesContext = createContext<ResourcesContextValue | null>(null);

/**
 * Hook to access resources context
 * @throws Error if used outside ResourcesProvider
 */
export function useResourcesContext(): ResourcesContextValue {
  const context = useContext(ResourcesContext);
  if (!context) {
    throw new Error("useResourcesContext must be used within ResourcesProvider");
  }
  return context;
}

/**
 * Provider component for resources context
 */
export function ResourcesProvider({
  children,
  value,
}: {
  children: ReactNode;
  value: ResourcesContextValue;
}) {
  return <ResourcesContext.Provider value={value}>{children}</ResourcesContext.Provider>;
}
