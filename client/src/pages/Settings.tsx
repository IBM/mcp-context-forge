import { useMemo, useState } from "react";
import { useIntl } from "react-intl";
import { useAuthContext } from "@/auth/AuthContext";
import { Redirect, useRouter } from "@/router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SettingsTabsProvider } from "@/components/settings/settings-toolbar";
import { Tokens } from "@/pages/Tokens";
import { Users } from "@/pages/Users";
import { Teams } from "@/pages/Teams";

// API Tokens is self-service (any authenticated user manages their own tokens),
// so it is the default tab and is always visible. Users and Teams are admin-only
// — visibility is evaluated per tab, not with a single page-level gate.
const DEFAULT_TAB = "tokens";

interface SettingsProps {
  tab?: string;
}

export function Settings({ tab }: SettingsProps) {
  const intl = useIntl();
  const { user } = useAuthContext();
  const { navigate } = useRouter();
  const isAdmin = Boolean(user?.is_admin);
  // Toolbar slot rendered on the tab row; the active tab portals its actions
  // (search, create, …) here so they sit inline with the tab triggers.
  const [toolbarEl, setToolbarEl] = useState<HTMLDivElement | null>(null);
  // The active tab hides the tab strip while showing a full-page form.
  const [tabsHidden, setTabsHidden] = useState(false);
  const tabsContext = useMemo(() => ({ toolbar: toolbarEl, setTabsHidden }), [toolbarEl]);

  const availableTabs = isAdmin ? ["tokens", "users", "teams"] : ["tokens"];

  if (tab !== undefined && !availableTabs.includes(tab)) {
    return <Redirect to="/app/settings" />;
  }
  const activeTab = tab ?? DEFAULT_TAB;

  // The tab row itself acts as the page header (per design), so there is no
  // standalone "Settings" title.
  return (
    <main className="space-y-6 p-6">
      <Tabs value={activeTab} onValueChange={(value) => navigate(`/app/settings/${value}`)}>
        {!tabsHidden && (
          <div className="flex items-end justify-between gap-4">
            <TabsList variant="line" className="w-auto">
              <TabsTrigger variant="line" value="tokens">
                {intl.formatMessage({ id: "settings.tabs.apiTokens" })}
              </TabsTrigger>
              {isAdmin && (
                <TabsTrigger variant="line" value="users">
                  {intl.formatMessage({ id: "settings.tabs.users" })}
                </TabsTrigger>
              )}
              {isAdmin && (
                <TabsTrigger variant="line" value="teams">
                  {intl.formatMessage({ id: "settings.tabs.teams" })}
                </TabsTrigger>
              )}
            </TabsList>
            {/* min-h-10 reserves the toolbar's populated height so the tab row
                keeps a constant height whether or not the active tab has filled
                the slot yet (prevents the tabs jumping on load). */}
            <div ref={setToolbarEl} className="flex min-h-10 shrink-0 items-center gap-3 pb-2" />
          </div>
        )}
        <SettingsTabsProvider value={tabsContext}>
          <TabsContent value="tokens">
            <Tokens />
          </TabsContent>
          {isAdmin && (
            <TabsContent value="users">
              <Users />
            </TabsContent>
          )}
          {isAdmin && (
            <TabsContent value="teams">
              <Teams />
            </TabsContent>
          )}
        </SettingsTabsProvider>
      </Tabs>
    </main>
  );
}
