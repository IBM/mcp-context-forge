import { useCallback, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/servers/ConfirmDialog";
import { SettingsToolbar, useHideSettingsTabs } from "@/components/settings/settings-toolbar";
import { TokensTable } from "@/components/tokens/TokensTable";
import { TokenForm } from "@/components/tokens/TokenForm";
import { TokenCreatedDialog } from "@/components/tokens/TokenCreatedDialog";
import { TokenIcon } from "@/components/tokens/TokenIcon";
import { useQuery } from "@/hooks/useQuery";
import { tokensApi } from "@/api/tokens";
import { parseApiError } from "@/lib/errorUtils";
import type { TeamsResponse } from "@/types/team";
import type { TokenListResponse, TokenResponse } from "@/types/token";

export function Tokens() {
  const intl = useIntl();
  const [view, setView] = useState<"list" | "create">("list");
  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<TokenResponse | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const { data, isLoading, error, setData, refetch } = useQuery<TokenListResponse>("/tokens");
  const tokens = useMemo(() => data?.tokens ?? [], [data?.tokens]);

  const { data: teamsData } = useQuery<TeamsResponse>("/teams");
  const teamNames = useMemo(
    () => new Map((teamsData?.teams ?? []).map((team) => [team.id, team.name])),
    [teamsData?.teams],
  );

  const handleCreated = useCallback(
    (accessToken: string, token: TokenResponse) => {
      setView("list");
      setCreatedToken(accessToken);
      setData((prev) =>
        prev
          ? { ...prev, tokens: [token, ...prev.tokens], total: prev.total + 1 }
          : { tokens: [token], total: 1, limit: 0, offset: 0 },
      );
    },
    [setData],
  );

  const handleDeleteConfirm = useCallback(async () => {
    if (!tokenToDelete) return;
    setIsDeleting(true);
    try {
      await tokensApi.delete(tokenToDelete.id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              tokens: prev.tokens.filter((token) => token.id !== tokenToDelete.id),
              total: Math.max(0, prev.total - 1),
            }
          : prev,
      );
      toast.success(
        intl.formatMessage({ id: "tokens.delete.success" }, { name: tokenToDelete.name }),
      );
      setTokenToDelete(null);
    } catch (err) {
      toast.error(parseApiError(err, intl.formatMessage({ id: "tokens.delete.error" })));
      // Reconcile with the server in case the optimistic assumption was wrong.
      void refetch();
    } finally {
      setIsDeleting(false);
    }
  }, [tokenToDelete, setData, intl, refetch]);

  // Hide the Settings tab strip (and its toolbar) while the full-page create
  // form is shown; the form carries its own Back button.
  useHideSettingsTabs(view === "create");

  if (view === "create") {
    return <TokenForm onCancel={() => setView("list")} onCreated={handleCreated} />;
  }

  return (
    <div className="space-y-6">
      {/* Always-present header keeps a consistent gap between the tab row and the
          content (card / table / states), matching the Users and Teams tabs. Its
          generate action portals onto the tab row and only shows once tokens
          exist (the empty state offers its own button); the sr-only title labels
          the section since the visible one is dropped per design. */}
      <header className="flex items-center justify-end">
        <h2 className="sr-only">{intl.formatMessage({ id: "tokens.table.caption" })}</h2>
        {!isLoading && !error && tokens.length > 0 && (
          <SettingsToolbar>
            <Button
              variant="default"
              className="h-7 rounded-sm px-4"
              onClick={() => setView("create")}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {intl.formatMessage({ id: "tokens.generate" })}
            </Button>
          </SettingsToolbar>
        )}
      </header>

      {isLoading ? (
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="flex items-center justify-center p-12"
        >
          <span className="sr-only">{intl.formatMessage({ id: "tokens.loading" })}</span>
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
        </div>
      ) : error ? (
        <div
          className="rounded-lg border border-destructive/20 bg-destructive/10 p-4"
          role="alert"
          aria-live="assertive"
        >
          <h3 className="mb-1 font-semibold">
            {intl.formatMessage({ id: "tokens.error.loading" })}
          </h3>
          <p className="text-destructive">{error.message}</p>
        </div>
      ) : tokens.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <TokenIcon />
            <h2 className="text-lg font-semibold text-foreground">
              {intl.formatMessage({ id: "tokens.form.title" })}
            </h2>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {intl.formatMessage({ id: "tokens.form.subtitle" })}
          </p>
          <Button className="mt-4" onClick={() => setView("create")}>
            {intl.formatMessage({ id: "tokens.generate" })}
          </Button>
        </div>
      ) : (
        <TokensTable
          tokens={tokens}
          teamNames={teamNames}
          onDeleteClick={(token) => setTokenToDelete(token)}
        />
      )}

      <TokenCreatedDialog token={createdToken} onClose={() => setCreatedToken(null)} />

      {tokenToDelete && (
        <ConfirmDialog
          open={tokenToDelete !== null}
          onOpenChange={(open) => {
            if (!open && !isDeleting) setTokenToDelete(null);
          }}
          title={intl.formatMessage({ id: "tokens.delete.title" })}
          description={intl.formatMessage({ id: "tokens.delete.description" })}
          confirmLabel={intl.formatMessage({ id: "tokens.delete.confirm" })}
          cancelLabel={intl.formatMessage({ id: "tokens.delete.cancel" })}
          variant="destructive"
          role="alertdialog"
          isLoading={isDeleting}
          closeOnConfirm={false}
          onConfirm={handleDeleteConfirm}
        />
      )}
    </div>
  );
}
