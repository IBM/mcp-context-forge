import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Box,
  Copy,
  EllipsisVertical,
  Filter,
  MessageSquareCode,
  PanelRightClose,
  Plus,
  Search,
  Users,
  Wrench,
} from "lucide-react";
import { MCPIcon } from "@/components/icons/MCPIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/loading";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { VirtualServer } from "@/types/server";
import type { ComponentFilter } from "@/components/gateways/types";
import {
  buildComponentItems,
  copyToClipboard,
  formatServerDateTime,
  formatVisibility,
  getComponentLabel,
  getTagDisplay,
  getVirtualServerEndpoint,
  truncateMiddle,
} from "@/components/gateways/utils";

function DetailRow({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-[96px_minmax(0,1fr)] items-start gap-4 ${className ?? ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function CopyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{truncateMiddle(value)}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="size-5 text-muted-foreground"
        aria-label={`Copy ${label}`}
        onClick={() => copyToClipboard(value)}
      >
        <Copy className="size-3.5" />
      </Button>
    </div>
  );
}

function getComponentIcon(type: Exclude<ComponentFilter, "all">) {
  if (type === "tools") return <Wrench className="size-3.5" />;
  if (type === "resources") return <Box className="size-3.5" />;
  return <MessageSquareCode className="size-3.5" />;
}

export function VirtualServerDetailsDrawer({
  server,
  isLoading,
  error,
  onAddComponents,
  onAddSources,
  onOpenChange,
}: {
  server: VirtualServer | null;
  isLoading: boolean;
  error: { message: string } | null;
  onAddComponents: () => void;
  onAddSources: () => void;
  onOpenChange: (open: boolean) => void;
}) {
  const endpoint = server ? getVirtualServerEndpoint(server.id) : "";
  const tags = (server?.tags ?? []).map(getTagDisplay);
  const [componentFilter, setComponentFilter] = useState<ComponentFilter>("all");

  useEffect(() => {
    setComponentFilter("all");
  }, [server?.id]);

  const componentItems = server ? buildComponentItems(server) : [];
  const visibleComponentItems =
    componentFilter === "all"
      ? componentItems
      : componentItems.filter((item) => item.type === componentFilter);
  const filterOptions: Array<{ value: ComponentFilter; label: string }> = [
    { value: "all", label: "All" },
    { value: "tools", label: "Tools" },
    { value: "resources", label: "Resources" },
    { value: "prompts", label: "Prompts" },
  ];

  return (
    <Sheet open={Boolean(server)} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="data-[side=right]:!w-[min(1236px,calc(100vw-2rem))] data-[side=right]:!max-w-none data-[side=right]:sm:!max-w-none gap-0 overflow-hidden border-l border-border bg-background p-0 text-[13px]"
      >
        {server && (
          <>
            <SheetHeader className="sr-only">
              <SheetTitle>{server.name} details</SheetTitle>
              <SheetDescription>Virtual server details and activity.</SheetDescription>
            </SheetHeader>

            <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0 overflow-y-auto px-6 py-8 lg:px-12">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
                      <MCPIcon className="size-4 [&_path]:fill-current" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <h2 className="truncate text-xl font-semibold text-foreground">
                          {server.name}
                        </h2>
                      </div>
                    </div>
                  </div>

                  <Button
                    type="button"
                    variant="default"
                    size="xs"
                    className="h-6 rounded-sm px-2 text-[13px]"
                    onClick={onAddSources}
                  >
                    <Plus className="size-3" />
                    Add sources
                  </Button>
                </div>

                <p className="mt-7 max-w-4xl text-[15px] leading-6 text-muted-foreground">
                  {server.description || "No description provided."}
                </p>

                <div className="my-8 h-px bg-border" />

                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-sm font-semibold text-foreground">Components</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 bg-background"
                    onClick={onAddComponents}
                  >
                    <Plus className="size-3.5" />
                    Add components
                  </Button>
                </div>

                <div className="mt-8 flex items-center justify-between gap-4">
                  <div className="flex min-w-0 items-center gap-6">
                    {filterOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`text-sm font-semibold transition-colors ${
                          componentFilter === option.value
                            ? "text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                        onClick={() => setComponentFilter(option.value)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-muted-foreground">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Search components"
                    >
                      <Search className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Filter components"
                    >
                      <Filter className="size-4" />
                    </Button>
                  </div>
                </div>

                {error && (
                  <div
                    role="alert"
                    className="mt-6 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                  >
                    {error.message}
                  </div>
                )}

                <div className="mt-5 divide-y divide-transparent">
                  {isLoading && (
                    <div className="flex items-center gap-2 py-8 text-muted-foreground">
                      <Loading />
                      <span>Loading server details...</span>
                    </div>
                  )}

                  {!isLoading &&
                    visibleComponentItems.map((item) => (
                      <div
                        key={item.id}
                        className="grid min-h-10 grid-cols-[128px_minmax(0,1fr)_minmax(180px,0.9fr)_24px] items-center gap-4 py-1 text-sm"
                      >
                        <Badge
                          variant="draft"
                          className="w-fit rounded-md px-2 py-0.5 text-[12px] font-medium text-muted-foreground"
                        >
                          <span className="mr-1.5 inline-flex">{getComponentIcon(item.type)}</span>
                          {getComponentLabel(item.type)}
                        </Badge>
                        <span className="min-w-0 truncate text-muted-foreground">{item.name}</span>
                        <span className="flex min-w-0 items-center gap-2 font-mono text-[13px] text-muted-foreground">
                          <span className="truncate">{item.secondary ?? item.name}</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Copy ${item.name}`}
                            className="size-5 text-muted-foreground"
                            onClick={() => copyToClipboard(item.secondary ?? item.name)}
                          >
                            <Copy className="size-3.5" />
                          </Button>
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Actions for ${item.name}`}
                          className="text-muted-foreground"
                        >
                          <EllipsisVertical className="size-4" />
                        </Button>
                      </div>
                    ))}

                  {!isLoading && visibleComponentItems.length === 0 && (
                    <div className="py-8 text-sm text-muted-foreground">
                      No {componentFilter === "all" ? "components" : componentFilter} found.
                    </div>
                  )}
                </div>
              </div>

              <aside className="relative border-t border-border bg-background lg:border-l lg:border-t-0">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Close virtual server details"
                  className="absolute right-3 top-3 text-muted-foreground"
                  onClick={() => onOpenChange(false)}
                >
                  <PanelRightClose className="size-4" />
                </Button>

                <div className="border-b border-border p-4 pt-8">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">
                    Virtual server details
                  </h3>

                  <dl className="space-y-4">
                    <DetailRow label="Status">
                      <span className="flex items-center gap-2">
                        <Activity className="size-3.5 text-emerald-400" />
                        {server.enabled ? "Active" : "Inactive"}
                      </span>
                    </DetailRow>
                    <DetailRow label="Visibility">
                      <span className="flex items-center gap-2">
                        <Users className="size-3.5 text-muted-foreground" />
                        {formatVisibility(server.visibility)}
                      </span>
                    </DetailRow>
                    <DetailRow label="Version">{server.version ?? "N/A"}</DetailRow>
                    <DetailRow label="Server ID">
                      <CopyValue label="server ID" value={server.id} />
                    </DetailRow>
                    <DetailRow label="URL">
                      <CopyValue label="URL" value={endpoint} />
                    </DetailRow>
                    <DetailRow label="Tags" className="items-center">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        {tags.map((tag) => (
                          <Badge
                            key={tag.key}
                            variant="outline"
                            className="rounded-full px-2 py-0 text-[11px] font-medium text-muted-foreground"
                          >
                            {tag.label}
                          </Badge>
                        ))}
                        <button
                          type="button"
                          className="text-[12px] text-muted-foreground hover:text-foreground"
                        >
                          + add
                        </button>
                      </div>
                    </DetailRow>
                  </dl>
                </div>

                <div className="p-4">
                  <h3 className="mb-7 text-sm font-semibold text-foreground">Activity</h3>
                  <dl className="space-y-4">
                    <DetailRow label="Created">{formatServerDateTime(server.createdAt)}</DetailRow>
                    <DetailRow label="Last modified">
                      {formatServerDateTime(server.updatedAt)}
                    </DetailRow>
                  </dl>
                </div>
              </aside>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
