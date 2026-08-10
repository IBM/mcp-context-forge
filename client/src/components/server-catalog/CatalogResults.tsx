import { useId, useState } from "react";
import type { ReactNode } from "react";
import { useIntl } from "react-intl";

import { EmptyStatePlaceholder } from "@/components/dashboard/EmptyStatePlaceholder";
import { StatusDot } from "@/components/dashboard/StatusDot";
import { ServerIcon } from "@/components/servers/ServerIcon";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CardTag } from "@/components/ui/card-tag";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CatalogServer } from "@/generated/types";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

function CatalogLogo({ server }: { server: CatalogServer }) {
  const [failed, setFailed] = useState(false);

  if (!server.logo_url || failed) {
    return (
      <div aria-hidden="true">
        <ServerIcon name={server.name} size="lg" />
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted"
    >
      <img
        src={server.logo_url}
        alt=""
        className="size-4 object-contain"
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

function CatalogCard({
  server,
  onView,
}: {
  server: CatalogServer;
  onView: (trigger: HTMLButtonElement) => void;
}) {
  const intl = useIntl();
  const headingId = useId();

  return (
    <li className="min-w-0">
      <Card className="h-full min-h-[200px] gap-0 rounded-xl border border-border bg-card p-0 py-0 shadow-none ring-0">
        <article className="flex h-full flex-col" aria-labelledby={headingId}>
          <CardContent className="flex flex-1 flex-col px-5 py-5">
            <div className="flex items-start justify-between gap-3">
              <CatalogLogo server={server} />
              {server.is_registered && (
                <StatusDot tone="success" className="text-xs text-muted-foreground">
                  {intl.formatMessage({ id: "mcpServer.catalog.connected" })}
                </StatusDot>
              )}
            </div>

            <h2 id={headingId} className="mt-4 truncate text-sm font-semibold text-foreground">
              {server.name}
            </h2>
            <p className="mt-3 line-clamp-2 min-h-8 text-[13px] leading-4 text-muted-foreground">
              {server.description}
            </p>

            <div className="mt-auto pt-4">
              <Button
                type="button"
                variant="outline"
                size="xs"
                aria-label={intl.formatMessage(
                  { id: "mcpServer.catalog.viewServer" },
                  { name: server.name },
                )}
                onClick={(event) => onView(event.currentTarget)}
              >
                {intl.formatMessage({ id: "mcpServer.catalog.view" })}
              </Button>
            </div>
          </CardContent>
        </article>
      </Card>
    </li>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-foreground">{children}</dd>
    </div>
  );
}

export function CatalogServerDetailsDialog({
  server,
  onOpenChange,
}: {
  server: CatalogServer | null;
  onOpenChange: (open: boolean) => void;
}) {
  const intl = useIntl();
  const tagsHeadingId = useId();

  return (
    <Dialog open={server !== null} onOpenChange={onOpenChange}>
      {server && (
        <DialogContent>
          <DialogHeader>
            <div className="mb-2 flex items-center gap-3">
              <CatalogLogo server={server} />
              <DialogTitle>{server.name}</DialogTitle>
            </div>
            <DialogDescription>{server.description}</DialogDescription>
          </DialogHeader>

          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-3 text-sm">
            <DetailRow label={intl.formatMessage({ id: "mcpServer.catalog.provider" })}>
              {server.provider}
            </DetailRow>
            <DetailRow label={intl.formatMessage({ id: "mcpServer.catalog.category" })}>
              {server.category}
            </DetailRow>
            <DetailRow label={intl.formatMessage({ id: "mcpServer.catalog.authentication" })}>
              {server.auth_type}
            </DetailRow>
            {server.transport && (
              <DetailRow label={intl.formatMessage({ id: "mcpServer.catalog.transport" })}>
                {server.transport}
              </DetailRow>
            )}
            <DetailRow label={intl.formatMessage({ id: "mcpServer.catalog.status" })}>
              {server.is_registered
                ? intl.formatMessage({ id: "mcpServer.catalog.connected" })
                : intl.formatMessage({ id: "mcpServer.catalog.notConnected" })}
            </DetailRow>
          </dl>

          {server.tags && server.tags.length > 0 && (
            <section aria-labelledby={tagsHeadingId}>
              <h3 id={tagsHeadingId} className="mb-2 text-sm font-medium text-muted-foreground">
                {intl.formatMessage({ id: "mcpServer.catalog.tags" })}
              </h3>
              <ul className="flex flex-wrap gap-2">
                {server.tags.map((tag) => (
                  <li key={tag}>
                    <CardTag variant="neutral">{tag}</CardTag>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </DialogContent>
      )}
    </Dialog>
  );
}

export function CatalogResults({
  servers,
  hasOpenServers,
  onView,
}: {
  servers: CatalogServer[];
  hasOpenServers: boolean;
  onView: (server: CatalogServer, trigger: HTMLButtonElement) => void;
}) {
  const intl = useIntl();
  const announcedCount = useDebouncedValue(servers.length, 300);

  return (
    <>
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {intl.formatMessage({ id: "mcpServer.catalog.resultCount" }, { count: announcedCount })}
      </p>
      {servers.length > 0 ? (
        <ul
          aria-label={intl.formatMessage({ id: "mcpServer.catalog.resultsLabel" })}
          className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-6"
        >
          {servers.map((server) => (
            <CatalogCard
              key={server.id}
              server={server}
              onView={(trigger) => onView(server, trigger)}
            />
          ))}
        </ul>
      ) : (
        <EmptyStatePlaceholder
          messageId={hasOpenServers ? "mcpServer.catalog.noResults" : "mcpServer.catalog.empty"}
        />
      )}
    </>
  );
}
