import { useIntl } from "react-intl";
import { useAuthContext } from "@/auth/AuthContext";
import { Redirect, useRouter } from "@/router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

  if (tab !== undefined && !(ADMIN_TABS as readonly string[]).includes(tab)) {
    return <Redirect to="/app/settings" />;
  }
  if (tab !== undefined && !isAdmin) {
    return <Redirect to="/app/settings" />;
  }

  return (
    <main className="space-y-6 p-6">
      <h1 className="text-xl font-semibold text-foreground">
        {intl.formatMessage({ id: "settings.title" })}
      </h1>
      {isAdmin && (
        <Tabs value={tab ?? "users"} onValueChange={(value) => navigate(`/app/settings/${value}`)}>
          <TabsList variant="line">
            <TabsTrigger variant="line" value="users">
              {intl.formatMessage({ id: "settings.tabs.users" })}
            </TabsTrigger>
            <TabsTrigger variant="line" value="teams">
              {intl.formatMessage({ id: "settings.tabs.teams" })}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="users">
            <Users />
          </TabsContent>
          <TabsContent value="teams">
            <Teams />
          </TabsContent>
        </Tabs>
      )}
    </main>
  );
}
