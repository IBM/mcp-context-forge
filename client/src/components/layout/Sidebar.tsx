import { useIntl } from "react-intl";
import { useRouter } from "../../router";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "../ui/sidebar";

interface NavItem {
  labelKey: string;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { labelKey: "navigation.dashboard", path: "/app/" },
  { labelKey: "navigation.gateways", path: "/app/gateways" },
  { labelKey: "navigation.servers", path: "/app/servers" },
  { labelKey: "navigation.tools", path: "/app/tools" },
  { labelKey: "navigation.resources", path: "/app/resources" },
  { labelKey: "navigation.prompts", path: "/app/prompts" },
  { labelKey: "navigation.agents", path: "/app/agents" },
  { labelKey: "navigation.users", path: "/app/users" },
  { labelKey: "navigation.teams", path: "/app/teams" },
  { labelKey: "navigation.tokens", path: "/app/tokens" },
  { labelKey: "navigation.llmProviders", path: "/app/llm/providers" },
  { labelKey: "navigation.llmModels", path: "/app/llm/models" },
  { labelKey: "navigation.metrics", path: "/app/metrics" },
  { labelKey: "navigation.observability", path: "/app/observability" },
  { labelKey: "navigation.plugins", path: "/app/plugins" },
  { labelKey: "navigation.performance", path: "/app/performance" },
  { labelKey: "navigation.maintenance", path: "/app/maintenance" },
  { labelKey: "navigation.settings", path: "/app/settings" },
];

export function AppSidebar() {
  const intl = useIntl();
  const { path, navigate } = useRouter();

  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader>
        <span className="px-2 text-sm font-semibold tracking-wide text-sidebar-foreground">
          ContextForge
        </span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>
            {intl.formatMessage({ id: "navigation.label" })}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map(({ labelKey, path: itemPath }) => {
                const isActive =
                  path === itemPath ||
                  (itemPath !== "/app/" && path.startsWith(itemPath));
                return (
                  <SidebarMenuItem key={itemPath}>
                    <SidebarMenuButton
                      isActive={isActive}
                      onClick={() => navigate(itemPath)}
                    >
                      <span>{intl.formatMessage({ id: labelKey })}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
