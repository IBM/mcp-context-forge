import { useMemo, useState } from "react";
import { useIntl } from "react-intl";
import { useAuthContext } from "@/auth/AuthContext";
import { Redirect, useRouter } from "@/router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SettingsTabsProvider } from "@/components/settings/settings-toolbar";
import { Users } from "@/pages/Users";
import { Teams } from "@/pages/Teams";

const ADMIN_TABS = ["users", "teams"] as const;

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

  // A tab segment is only valid for admins requesting a known tab; anything
  // else (unknown tab, or a non-admin deep-linking a tab) falls back to the
  // Settings root.
  const isValidTab =
    tab === undefined || (isAdmin && (ADMIN_TABS as readonly string[]).includes(tab));
  if (!isValidTab) {
    return <Redirect to="/app/settings" />;
  }

  // Non-admins have no tabs to show; keep a visible heading so the page isn't
  // blank. Admins get the tabbed shell, where the tab row itself acts as the
  // page header (per design), so the standalone "Settings" title is dropped.
  if (!isAdmin) {
    return (
      <main className="space-y-6 p-6">
        <h1 className="text-xl font-semibold text-foreground">
          {intl.formatMessage({ id: "settings.title" })}
        </h1>
      </main>
    );
  }

  return (
    <main className="space-y-6 p-6">
      <Tabs value={tab ?? "users"} onValueChange={(value) => navigate(`/app/settings/${value}`)}>
        {!tabsHidden && (
          <div className="flex items-end justify-between gap-4">
            <TabsList variant="line" className="w-auto">
              <TabsTrigger variant="line" value="users">
                {intl.formatMessage({ id: "settings.tabs.users" })}
              </TabsTrigger>
              <TabsTrigger variant="line" value="teams">
                {intl.formatMessage({ id: "settings.tabs.teams" })}
              </TabsTrigger>
            </TabsList>
            {/* min-h-10 reserves the toolbar's populated height so the tab row
                keeps a constant height whether or not the active tab has filled
                the slot yet (prevents the tabs jumping on load). */}
            <div ref={setToolbarEl} className="flex shrink-0 items-center gap-3 pb-2 min-h-10" />
          </div>
        )}
        <SettingsTabsProvider value={tabsContext}>
          <TabsContent value="users">
            <Users />
          </TabsContent>
          <TabsContent value="teams">
            <Teams />
          </TabsContent>
        </SettingsTabsProvider>
      </Tabs>
    </main>
  );
}
